#!/usr/bin/env python3
"""
Aggregate grading results into a leaderboard.

Two modes:

1. Legacy/headline (no args): reproduces the original headline board — each
   skill (+ baseline) on the 27 core_subset evals, source-only single pass, per
   model, selected by directory-name/metadata heuristics. Runs created by the
   new pipeline (run_metadata has "experiment") are EXCLUDED here; they are
   selected explicitly via manifests instead.
   Outputs results/benchmark.json, results/history/, site/data.json.

2. Experiment (--experiment NAME [NAME...]): aggregates exactly the run dirs
   listed in results/experiments/<NAME>.json. Repetitions of the same
   (skill, eval) cell are AVERAGED (mean across reps), and the leaderboard
   reports a bootstrap 95% CI on micro-recall (resampling evals, seed 42).
   Outputs results/experiments/<NAME>.board.json (+ prints). Use --publish to
   also write site/data.json from the experiment board.

Micro metrics (pool findings, then divide) remain the headline numbers; the
per-eval spread is kept as stddev context. See FINDINGS.md §2.

Usage:
  python3 scripts/aggregate.py
  python3 scripts/aggregate.py --experiment sonnet-rep3
"""

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent
RESULTS_DIR = PROJ_ROOT / "results" / "runs"
EVALS_DIR = PROJ_ROOT / "evals"
EXP_DIR = PROJ_ROOT / "results" / "experiments"

BOOTSTRAP_ITERS = 2000
BOOTSTRAP_SEED = 42


def _core_subset() -> set:
    try:
        data = json.loads((EVALS_DIR / "core_subset.json").read_text())
        return {e["eval_id"] for e in data["evals"]}
    except Exception:
        return set()


def _meta(run_dir) -> dict:
    """Authoritative run identity from run_metadata.json (orchestrator-written).
    Falls back to grading.json's embedded run_metadata only if that file is
    absent — never the other way around, because a grader subagent can inject a
    bogus run_metadata into grading.json (e.g. model="sonnet")."""
    mp = run_dir / "run_metadata.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    gp = run_dir / "grading.json"
    if gp.exists():
        try:
            return json.loads(gp.read_text()).get("run_metadata", {}) or {}
        except Exception:
            pass
    return {}


def _grading_entry(run_dir, eval_id, m, grading):
    skill_dir_name = run_dir.parent.parent.name
    skill_name = m.get("skill") or skill_dir_name.replace("__", "/")
    meta_path = EVALS_DIR / eval_id / "metadata.json"
    eval_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return {
        "skill": skill_name,
        "skill_path": m.get("skill_path", ""),
        "eval_id": eval_id,
        "model": m.get("model", "unknown"),
        "tooling": m.get("tooling", "disabled"),
        "is_baseline": bool(m.get("is_baseline")),
        "rep": m.get("rep", 1),
        "run_dir": str(run_dir),
        "timestamp": run_dir.name,
        "grading": grading,
        "eval_meta": eval_meta,
    }


def load_headline_gradings() -> list:
    """The HEADLINE comparison: each skill (+ baseline) on the 27 core_subset
    evals, source-only single pass, per model. Tooling A/B, multi-pass, and
    manifest-selected experiment runs are excluded so they don't jumble the
    board."""
    gradings = []
    if not RESULTS_DIR.exists():
        return gradings
    core = _core_subset()

    for skill_dir in sorted(RESULTS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        for eval_dir in sorted(skill_dir.iterdir()):
            if not eval_dir.is_dir() or eval_dir.name not in core:
                continue
            eval_id = eval_dir.name

            # Per model, collect original source-only runs: tooling disabled,
            # not pass 2, not the tooling A/B's tools-off arm (dirs end "D"),
            # not new-pipeline experiment runs (manifest-selected instead).
            by_model = defaultdict(list)  # model -> [(run_dir, meta)]
            for d in sorted(x for x in eval_dir.iterdir() if x.is_dir()):
                if not (d / "grading.json").exists():
                    continue
                m = _meta(d)
                if m.get("experiment"):
                    continue
                if m.get("tooling", "disabled") != "disabled":
                    continue
                if m.get("pass") == 2 or d.name.endswith("D"):
                    continue
                by_model[m.get("model", "unknown")].append((d, m))

            for model, runs in by_model.items():
                for d, m in runs:
                    try:
                        grading = json.loads((d / "grading.json").read_text())
                    except Exception:
                        continue
                    gradings.append(_grading_entry(d, eval_id, m, grading))
    return gradings


def load_experiment_gradings(names) -> tuple:
    """All graded cells of the given experiment manifests. Returns
    (gradings, n_missing)."""
    gradings, missing = [], 0
    for name in names:
        manifest = json.loads((EXP_DIR / f"{name}.json").read_text())
        for c in manifest["cells"]:
            run_dir = PROJ_ROOT / c["run_dir"]
            gp = run_dir / "grading.json"
            if not gp.exists():
                missing += 1
                continue
            try:
                grading = json.loads(gp.read_text())
            except Exception:
                missing += 1
                continue
            m = _meta(run_dir)
            gradings.append(_grading_entry(run_dir, c["eval_id"], m, grading))
    return gradings, missing


def compute_stats(values: list) -> dict:
    """Compute mean and stddev for a list of values."""
    if not values:
        return {"mean": 0, "stddev": 0, "min": 0, "max": 0, "n": 0}
    n = len(values)
    mean = sum(values) / n
    if n > 1:
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)
        stddev = math.sqrt(variance)
    else:
        stddev = 0
    return {
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "n": n,
    }


def bootstrap_recall_ci(per_eval: list) -> list:
    """95% CI on micro-recall by resampling EVALS with replacement (clusters,
    not findings — findings within an eval are correlated). Deterministic."""
    pairs = [(e["_found_mean"], e["total"]) for e in per_eval if e["total"]]
    if len(pairs) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    m = len(pairs)
    stats = []
    for _ in range(BOOTSTRAP_ITERS):
        s = [pairs[rng.randrange(m)] for _ in range(m)]
        f = sum(p[0] for p in s)
        t = sum(p[1] for p in s)
        stats.append(f / t if t else 0.0)
    stats.sort()
    lo = stats[int(0.025 * BOOTSTRAP_ITERS)]
    hi = stats[min(int(0.975 * BOOTSTRAP_ITERS), BOOTSTRAP_ITERS - 1)]
    return [round(lo, 4), round(hi, 4)]


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def aggregate(gradings: list, experiment=None) -> dict:
    """Build the benchmark. Repetitions of the same (skill, model, tooling,
    eval) cell are averaged before pooling."""
    # Per-(skill, model) token totals for the headline runs, if reconstructed
    # (results/token_usage.json, written by scripts/persist_token_usage.py).
    tok_map = {}
    tpath = PROJ_ROOT / "results" / "token_usage.json"
    if tpath.exists():
        try:
            tok_map = json.loads(tpath.read_text())
        except Exception:
            tok_map = {}

    # Group by (skill, model, tooling): each combination is its own row.
    by_skill = defaultdict(list)
    for g in gradings:
        by_skill[(g["skill"], g.get("model", "unknown"),
                  g.get("tooling", "disabled"))].append(g)

    leaderboard = []
    for (skill_name, group_model, group_tooling), runs in sorted(by_skill.items()):
        # ---- collapse repetitions: eval_id -> list of runs
        by_eval = defaultdict(list)
        for run in runs:
            by_eval[run["eval_id"]].append(run)

        recalls, precisions, f1s = [], [], []
        durations, costs, total_tokens_list = [], [], []
        tok_run_sum = tok_run_found = 0.0
        tok_run_n = 0
        models_seen = set()
        per_eval = []
        found_sum = total_sum = fp_sum = 0.0
        rep_counts = []

        for eval_id in sorted(by_eval):
            cell_runs = by_eval[eval_id]
            rep_counts.append(len(cell_runs))
            cr, cp, cf1, cfound, cfp = [], [], [], [], []
            totals = []
            for run in cell_runs:
                summary = run["grading"].get("summary", {})
                recall = summary.get("recall", 0)
                precision = summary.get("precision", 0)
                f1 = (2 * precision * recall / (precision + recall)
                      if (recall + precision) > 0 else 0)
                cr.append(recall)
                cp.append(precision)
                cf1.append(f1)
                cfound.append(summary.get("found", 0))
                cfp.append(summary.get("false_positives", 0))
                totals.append(summary.get("total", 0))

                # Extract run metadata (new format) or timing (old format)
                run_meta = run["grading"].get("run_metadata", {})
                timing = run["grading"].get("timing", {})
                meta = run_meta or timing
                duration = meta.get("duration_seconds", 0)
                if duration:
                    durations.append(duration)
                cost = meta.get("total_cost_usd", 0)
                if cost:
                    costs.append(cost)
                model = meta.get("model", "")
                if model:
                    models_seen.add(model)
                tokens = meta.get("tokens") or {}
                tok_total = tokens.get("total", 0) or (
                    tokens.get("input", 0) + tokens.get("output", 0)
                    + tokens.get("cache_read", 0) + tokens.get("cache_creation", 0))
                if tok_total:
                    total_tokens_list.append(tok_total)
                    tok_run_sum += tok_total
                    tok_run_found += summary.get("found", 0)
                    tok_run_n += 1

            total = max(totals) if totals else 0
            found_mean = _mean(cfound)
            fp_mean = _mean(cfp)
            recall_mean = _mean(cr)
            precision_mean = _mean(cp)
            f1_mean = _mean(cf1)

            recalls.append(recall_mean)
            precisions.append(precision_mean)
            f1s.append(f1_mean)
            found_sum += found_mean
            total_sum += total
            fp_sum += fp_mean

            last = cell_runs[-1]
            per_eval.append({
                "eval_id": eval_id,
                "project_name": last["eval_meta"].get("project_name", ""),
                "recall": round(recall_mean, 4),
                "precision": round(precision_mean, 4),
                "f1": round(f1_mean, 4),
                "found": round(found_mean, 2),
                "total": total,
                "false_positives": round(fp_mean, 2),
                "reps": len(cell_runs),
                "recall_min": round(min(cr), 4) if cr else 0,
                "recall_max": round(max(cr), 4) if cr else 0,
                "timestamp": last["timestamp"],
                "cost_usd": None,
                "grading_cost_usd": None,
                "tokens": None,
                "model": group_model,
                "_found_mean": found_mean,
            })

        skill_path = runs[0].get("skill_path", "")

        # MICRO metrics (pool all findings, then divide) are the headline
        # numbers — the macro per-eval mean has too little power to rank these
        # (see FINDINGS.md §2). Per-eval spread kept as stddev context.
        micro_recall = found_sum / total_sum if total_sum else 0
        micro_precision = (found_sum / (found_sum + fp_sum)
                           if (found_sum + fp_sum) else 0)
        micro_f1 = (2 * micro_precision * micro_recall / (micro_precision + micro_recall)
                    if (micro_precision + micro_recall) else 0)
        recall_stats = compute_stats(recalls)
        recall_stats["mean"] = round(micro_recall, 4)
        recall_stats["ci95"] = bootstrap_recall_ci(per_eval)
        precision_stats = compute_stats(precisions)
        precision_stats["mean"] = round(micro_precision, 4)
        f1_stats = compute_stats(f1s)
        f1_stats["mean"] = round(micro_f1, 4)

        for e in per_eval:
            e.pop("_found_mean", None)

        # Token efficiency: total tokens spent across the eval set per REAL
        # finding caught (lower = cheaper to surface a known bug).
        tok = tok_map.get(f"{skill_name.replace('/', '__')}|{group_model}", {})
        tok_total = tok.get("sum_total", 0)
        if tok_total:
            tok_per_finding = round(tok_total / found_sum) if found_sum else None
            tok_per_audit = round(tok_total / tok["n"]) if tok.get("n") else None
        else:
            # Fall back to per-run tokens from run_metadata (recorded by the
            # orchestrator or reconstructed by scripts/backfill_tokens.py).
            # Numerator and denominator both range over the token-covered runs
            # only, so partial transcript coverage doesn't skew the ratio.
            tok_total = round(tok_run_sum) or None
            tok_per_audit = round(tok_run_sum / tok_run_n) if tok_run_n else None
            tok_per_finding = (round(tok_run_sum / tok_run_found)
                               if (tok_run_sum and tok_run_found) else None)

        entry = {
            "skill": skill_name,
            "skill_path": skill_path,
            "evals_run": len(by_eval),
            "reps": max(rep_counts) if rep_counts else 1,
            "model": group_model,
            "tooling": group_tooling,
            "is_baseline": runs[0].get("is_baseline", False),
            "experiment": experiment,
            "recall": recall_stats,
            "precision": precision_stats,
            "f1": f1_stats,
            "found": round(found_sum, 2),
            "total": int(total_sum),
            "false_positives": round(fp_sum, 2),
            "tokens_total": tok_total or None,
            "tokens_per_audit": tok_per_audit,
            "tokens_per_finding": tok_per_finding,
            "duration": compute_stats(durations) if durations else None,
            "cost_usd": compute_stats(costs) if costs else None,
            "tokens": compute_stats(total_tokens_list) if total_tokens_list else None,
            "per_eval": per_eval,
        }
        leaderboard.append(entry)

    # Sort by micro-recall descending (the metric we trust)
    leaderboard.sort(key=lambda x: x["recall"]["mean"], reverse=True)
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "experiment": experiment,
        "total_skills": len(leaderboard),
        "total_evals_available": len([p for p in EVALS_DIR.iterdir() if p.is_dir()]),
        "leaderboard": leaderboard,
    }


def print_board(benchmark):
    print(f"\nLeaderboard:")
    header = (f"{'Rank':<5}{'Skill':<31}{'Model':<8}{'Catch%':<8}"
              f"{'95% CI':<16}{'Prec':<7}{'Found':<9}{'Reps':<5}{'N':<4}")
    print(header)
    print("-" * len(header))
    for entry in benchmark["leaderboard"]:
        model = entry.get("model", "") or ""
        model_short = ("opus" if "opus" in model else
                       "sonnet" if "sonnet" in model else (model[:7] or "-"))
        found_str = f"{entry.get('found', 0):g}/{entry.get('total', 0)}"
        ci = entry["recall"].get("ci95")
        ci_str = f"[{ci[0]:.0%},{ci[1]:.0%}]" if ci else "-"
        print(f"{entry['rank']:<5}{entry['skill']:<31}{model_short:<8}"
              f"{entry['recall']['mean']:<8.1%}{ci_str:<16}"
              f"{entry['precision']['mean']:<7.1%}"
              f"{found_str:<9}{entry.get('reps', 1):<5}{entry['evals_run']:<4}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", nargs="*",
                    help="aggregate these experiment manifests instead of the "
                         "legacy headline heuristics")
    ap.add_argument("--publish", action="store_true",
                    help="with --experiment: also write site/data.json")
    args = ap.parse_args()

    if args.experiment:
        gradings, missing = load_experiment_gradings(args.experiment)
        if missing:
            print(f"WARNING: {missing} cells in the manifest(s) have no valid "
                  f"grading.json — run validate_runs.py and re-run the holes.")
        if not gradings:
            sys.exit("no graded cells found for the given experiment(s)")
        name = "+".join(args.experiment)
        benchmark = aggregate(gradings, experiment=name)
        out = EXP_DIR / f"{name}.board.json"
        out.write_text(json.dumps(benchmark, indent=2))
        print(f"Experiment board: {len(gradings)} graded cells -> {out}")
        if args.publish:
            (PROJ_ROOT / "site" / "data.json").write_text(
                json.dumps(benchmark, indent=2))
            print("published to site/data.json")
        print_board(benchmark)
        return

    gradings = load_headline_gradings()
    if not gradings:
        print("No grading results found. Run some evals first.")
        sys.exit(0)

    benchmark = aggregate(gradings)

    benchmark_path = PROJ_ROOT / "results" / "benchmark.json"
    with open(benchmark_path, "w") as f:
        json.dump(benchmark, f, indent=2)

    history_dir = PROJ_ROOT / "results" / "history"
    history_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    with open(history_dir / f"benchmark_{ts}.json", "w") as f:
        json.dump(benchmark, f, indent=2)

    site_dir = PROJ_ROOT / "site"
    site_dir.mkdir(exist_ok=True)
    with open(site_dir / "data.json", "w") as f:
        json.dump(benchmark, f, indent=2)

    print(f"Benchmark generated: {benchmark['total_skills']} rows")
    print("Headline board: core_subset (27 evals), source-only single pass, "
          "ranked by MICRO-recall.")
    print_board(benchmark)


if __name__ == "__main__":
    main()
