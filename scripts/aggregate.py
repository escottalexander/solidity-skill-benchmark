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


def load_all_gradings() -> list:
    """Load all grading.json files from results."""
    gradings = []

    if not RESULTS_DIR.exists():
        return gradings

    for skill_dir in sorted(RESULTS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue

        for eval_dir in sorted(skill_dir.iterdir()):
            if not eval_dir.is_dir():
                continue
            eval_id = eval_dir.name

            # Select the most recent run per (model, tooling) that has a
            # grading.json. Keyed on both axes so a failed re-run can't shadow a
            # success, and sonnet/opus and tools-on/tools-off all survive as
            # distinct cells rather than the newest overwriting the others.
            latest_by_key = {}  # (model, tooling) -> run_dir Path (last = latest ts)
            for d in sorted(x for x in eval_dir.iterdir() if x.is_dir()):
                if not (d / "grading.json").exists():
                    continue
                latest_by_key[(_run_model(d), _run_tooling(d))] = d

            for (model, tooling), latest_run in latest_by_key.items():
                with open(latest_run / "grading.json") as f:
                    grading = json.load(f)

                run_meta = grading.get("run_metadata", {})
                if not run_meta:
                    meta_file = latest_run / "run_metadata.json"
                    if meta_file.exists():
                        with open(meta_file) as f:
                            run_meta = json.load(f)

                skill_name = (run_meta.get("skill")
                              or skill_dir.name.replace("__", "/"))
                skill_path = run_meta.get("skill_path", "")

                meta_path = EVALS_DIR / eval_id / "metadata.json"
                eval_meta = {}
                if meta_path.exists():
                    with open(meta_path) as f:
                        eval_meta = json.load(f)

                gradings.append({
                    "skill": skill_name,
                    "skill_path": skill_path,
                    "eval_id": eval_id,
                    "model": model,
                    "tooling": tooling,
                    "run_dir": str(latest_run),
                    "timestamp": latest_run.name,
                    "grading": grading,
                    "eval_meta": eval_meta,
                })

    return gradings


def _run_model(run_dir) -> str:
    """Read the model a run used, from grading.json or run_metadata.json."""
    gp = run_dir / "grading.json"
    if gp.exists():
        try:
            m = json.load(open(gp)).get("run_metadata", {}).get("model")
            if m:
                return m
        except Exception:
            pass
    mf = run_dir / "run_metadata.json"
    if mf.exists():
        try:
            m = json.load(open(mf)).get("model")
            if m:
                return m
        except Exception:
            pass
    return "unknown"


def _run_tooling(run_dir) -> str:
    """Read the tooling mode (enabled/disabled) for a run; default disabled."""
    gp = run_dir / "grading.json"
    if gp.exists():
        try:
            t = json.load(open(gp)).get("run_metadata", {}).get("tooling")
            if t:
                return t
        except Exception:
            pass
    mf = run_dir / "run_metadata.json"
    if mf.exists():
        try:
            t = json.load(open(mf)).get("tooling")
            if t:
                return t
        except Exception:
            pass
    return "disabled"


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

        for run in runs:
            summary = run["grading"].get("summary", {})
            recall = summary.get("recall", 0)
            precision = summary.get("precision", 0)
            recalls.append(recall)
            precisions.append(precision)

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

        entry = {
            "skill": skill_name,
            "skill_path": skill_path,
            "evals_run": len(runs),
            "model": group_model,
            "tooling": group_tooling,
            "recall": compute_stats(recalls),
            "precision": compute_stats(precisions),
            "f1": compute_stats(f1s),
            "duration": compute_stats(durations) if durations else None,
            "cost_usd": compute_stats(costs) if costs else None,
            "tokens": compute_stats(total_tokens_list) if total_tokens_list else None,
            "per_eval": sorted(per_eval, key=lambda x: x["eval_id"]),
        }
        leaderboard.append(entry)

    # Sort by F1 mean descending
    leaderboard.sort(key=lambda x: x["f1"]["mean"], reverse=True)

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
    print(f"Benchmark generated: {benchmark['total_skills']} skills evaluated")
    print(f"\nLeaderboard:")
    header = (f"{'Rank':<6}{'Skill':<35}{'Model':<22}{'Tools':<10}{'F1':<9}"
              f"{'Recall':<9}{'Prec':<9}{'Tokens':<12}{'Time':<8}{'N':<4}")
    print(header)
    print("-" * len(header))
    for entry in benchmark["leaderboard"]:
        model = entry.get("model", "") or ""
        if isinstance(model, list):
            model = ",".join(model)
        model_short = model[:21] if model else "-"
        tooling = entry.get("tooling", "disabled")
        tool_str = "ON" if tooling == "enabled" else "off"
        tokens = entry.get("tokens")
        tok_str = f"{tokens['mean']:,.0f}" if tokens and tokens["n"] else "-"
        dur = entry.get("duration")
        dur_str = f"{dur['mean']:.0f}s" if dur and dur["n"] else "-"
        print(f"{entry['rank']:<6}{entry['skill']:<35}{model_short:<22}{tool_str:<10}"
              f"{entry['f1']['mean']:<9.1%}{entry['recall']['mean']:<9.1%}"
              f"{entry['precision']['mean']:<9.1%}{tok_str:<12}"
              f"{dur_str:<8}{entry['evals_run']:<4}")


if __name__ == "__main__":
    main()
