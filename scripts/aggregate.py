#!/usr/bin/env python3
"""
Aggregate all grading results into a leaderboard.

Reads results/runs/{skill}/{eval}/{timestamp}/grading.json
Outputs results/benchmark.json and site/data.json

Usage: python3 scripts/aggregate.py
"""

import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent
RESULTS_DIR = PROJ_ROOT / "results" / "runs"
EVALS_DIR = PROJ_ROOT / "evals"


def _core_subset() -> set:
    try:
        data = json.loads((EVALS_DIR / "core_subset.json").read_text())
        return {e["eval_id"] for e in data["evals"]}
    except Exception:
        return set()


def load_all_gradings() -> list:
    """Load the HEADLINE comparison: each skill (+ baseline) on the 27
    core_subset evals, source-only single pass, per model. Deliberately scoped
    to one apples-to-apples comparison — the tooling A/B and multi-pass runs are
    separate experiments (see scripts/tooling_compare.py, multipass_analysis.py)
    and are excluded here so they don't jumble the board."""
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

            # Per model, pick the original source-only run: tooling disabled,
            # not pass 2, not the tooling A/B's tools-off arm (its dirs end "D").
            latest_by_model = {}  # model -> (run_dir, meta)
            for d in sorted(x for x in eval_dir.iterdir() if x.is_dir()):
                if not (d / "grading.json").exists():
                    continue
                m = _meta(d)
                if m.get("tooling", "disabled") != "disabled":
                    continue
                if m.get("pass") == 2 or d.name.endswith("D"):
                    continue
                model = m.get("model", "unknown")
                latest_by_model[model] = (d, m)

            for model, (latest_run, m) in latest_by_model.items():
                grading = json.loads((latest_run / "grading.json").read_text())
                skill_name = m.get("skill") or skill_dir.name.replace("__", "/")
                meta_path = EVALS_DIR / eval_id / "metadata.json"
                eval_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
                gradings.append({
                    "skill": skill_name,
                    "skill_path": m.get("skill_path", ""),
                    "eval_id": eval_id,
                    "model": model,
                    "tooling": "disabled",
                    "is_baseline": bool(m.get("is_baseline")),
                    "run_dir": str(latest_run),
                    "timestamp": latest_run.name,
                    "grading": grading,
                    "eval_meta": eval_meta,
                })

    return gradings


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


def aggregate(gradings: list) -> dict:
    """Build the full benchmark from all gradings."""
    # Group by (skill, model, tooling) so each combination is its own
    # leaderboard row: sonnet/opus and tools-on/tools-off never collapse.
    by_skill = defaultdict(list)
    for g in gradings:
        by_skill[(g["skill"], g.get("model", "unknown"),
                  g.get("tooling", "disabled"))].append(g)

    # Build leaderboard
    leaderboard = []
    for (skill_name, group_model, group_tooling), runs in sorted(by_skill.items()):
        recalls = []
        precisions = []
        f1s = []
        durations = []
        costs = []
        total_tokens_list = []
        models_seen = set()
        per_eval = []
        found_sum = total_sum = fp_sum = 0

        for run in runs:
            summary = run["grading"].get("summary", {})
            recall = summary.get("recall", 0)
            precision = summary.get("precision", 0)
            recalls.append(recall)
            precisions.append(precision)
            found_sum += summary.get("found", 0)
            total_sum += summary.get("total", 0)
            fp_sum += summary.get("false_positives", 0)

            if recall + precision > 0:
                f1 = 2 * (precision * recall) / (precision + recall)
            else:
                f1 = 0
            f1s.append(f1)

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

            tokens = meta.get("tokens", {})
            # Agent-led runs record a single {"total": N} (from the subagent
            # usage block); legacy claude -p runs record input/output/cache_*.
            tok_total = tokens.get("total", 0) or (
                tokens.get("input", 0) + tokens.get("output", 0)
                + tokens.get("cache_read", 0) + tokens.get("cache_creation", 0))
            if tok_total:
                total_tokens_list.append(tok_total)

            # Also capture grading cost
            grading_meta = run["grading"].get("grading_meta", {})
            grading_cost = grading_meta.get("total_cost_usd", 0)

            per_eval.append({
                "eval_id": run["eval_id"],
                "project_name": run["eval_meta"].get("project_name", ""),
                "recall": recall,
                "precision": precision,
                "f1": round(f1, 4),
                "found": summary.get("found", 0),
                "total": summary.get("total", 0),
                "false_positives": summary.get("false_positives", 0),
                "timestamp": run["timestamp"],
                "cost_usd": round(cost, 4) if cost else None,
                "grading_cost_usd": round(grading_cost, 4) if grading_cost else None,
                "tokens": tokens if tokens else None,
                "model": model or None,
            })

        # Get skill_path from the first run (all runs share the same skill)
        skill_path = runs[0].get("skill_path", "")

        # MICRO metrics (pool all findings, then divide) are the headline numbers
        # — the macro per-eval mean has too little power to rank these (see
        # FINDINGS.md §2). We keep the per-eval spread as the stddev for context.
        micro_recall = found_sum / total_sum if total_sum else 0
        micro_precision = (found_sum / (found_sum + fp_sum)
                           if (found_sum + fp_sum) else 0)
        micro_f1 = (2 * micro_precision * micro_recall / (micro_precision + micro_recall)
                    if (micro_precision + micro_recall) else 0)
        recall_stats = compute_stats(recalls); recall_stats["mean"] = round(micro_recall, 4)
        precision_stats = compute_stats(precisions); precision_stats["mean"] = round(micro_precision, 4)
        f1_stats = compute_stats(f1s); f1_stats["mean"] = round(micro_f1, 4)

        entry = {
            "skill": skill_name,
            "skill_path": skill_path,
            "evals_run": len(runs),
            "model": group_model,
            "tooling": group_tooling,
            "is_baseline": runs[0].get("is_baseline", False),
            "recall": recall_stats,
            "precision": precision_stats,
            "f1": f1_stats,
            "found": found_sum,
            "total": total_sum,
            "false_positives": fp_sum,
            "duration": compute_stats(durations) if durations else None,
            "cost_usd": compute_stats(costs) if costs else None,
            "tokens": compute_stats(total_tokens_list) if total_tokens_list else None,
            "per_eval": sorted(per_eval, key=lambda x: x["eval_id"]),
        }
        leaderboard.append(entry)

    # Sort by micro-recall descending (the metric we trust)
    leaderboard.sort(key=lambda x: x["recall"]["mean"], reverse=True)

    # Add rank
    for i, entry in enumerate(leaderboard):
        entry["rank"] = i + 1

    benchmark = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_skills": len(leaderboard),
        "total_evals_available": len(list(EVALS_DIR.iterdir())) - 1,  # minus evals.json
        "leaderboard": leaderboard,
    }

    return benchmark


def main():
    gradings = load_all_gradings()

    if not gradings:
        print("No grading results found. Run some evals first.")
        print("Usage: ./scripts/run_eval.sh <skill.md> <eval_id>")
        sys.exit(0)

    benchmark = aggregate(gradings)

    # Save benchmark
    benchmark_path = PROJ_ROOT / "results" / "benchmark.json"
    with open(benchmark_path, "w") as f:
        json.dump(benchmark, f, indent=2)

    # Save history snapshot
    history_dir = PROJ_ROOT / "results" / "history"
    history_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    with open(history_dir / f"benchmark_{ts}.json", "w") as f:
        json.dump(benchmark, f, indent=2)

    # Generate site data
    site_dir = PROJ_ROOT / "site"
    site_dir.mkdir(exist_ok=True)
    with open(site_dir / "data.json", "w") as f:
        json.dump(benchmark, f, indent=2)

    # Print summary
    print(f"Benchmark generated: {benchmark['total_skills']} rows "
          f"(6 skills + baseline x 2 models)")
    print("Headline board: core_subset (27 evals), source-only single pass, "
          "ranked by MICRO-recall.")
    print(f"\nLeaderboard:")
    header = (f"{'Rank':<6}{'Skill':<33}{'Model':<9}{'Recall':<9}"
              f"{'Prec':<9}{'F1':<9}{'Found':<9}{'N':<4}")
    print(header)
    print("-" * len(header))
    for entry in benchmark["leaderboard"]:
        model = entry.get("model", "") or ""
        if isinstance(model, list):
            model = ",".join(model)
        model_short = ("opus" if "opus" in model else
                       "sonnet" if "sonnet" in model else (model[:8] or "-"))
        found_str = f"{entry.get('found', 0)}/{entry.get('total', 0)}"
        print(f"{entry['rank']:<6}{entry['skill']:<33}{model_short:<9}"
              f"{entry['recall']['mean']:<9.1%}{entry['precision']['mean']:<9.1%}"
              f"{entry['f1']['mean']:<9.1%}{found_str:<9}{entry['evals_run']:<4}")


if __name__ == "__main__":
    main()
