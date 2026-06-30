#!/usr/bin/env python3
"""Persist per-(skill, model) token totals for the HEADLINE leaderboard runs,
so aggregate.py can show a tokens-per-finding column. Tokens aren't stored in
run_metadata (only reconstructable from transcripts), so this reads the agent
transcripts once and writes results/token_usage.json.

Only counts auditor transcripts whose run is on the headline board (core_subset
eval, source-only, not pass 2, not the tooling-off arm) — the same scope as
aggregate.load_all_gradings — so the numbers line up with the board.

Usage: python3 scripts/persist_token_usage.py <workflow_transcript_dir> [more...]
"""
import json
import glob
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "results" / "token_usage.json"
CORE = {e["eval_id"] for e in json.loads(
    (PROJ / "evals" / "core_subset.json").read_text())["evals"]}


def scan_transcript(path):
    """Return (response_md_path, total_tokens) for an auditor transcript, else None."""
    rp = None
    tot = 0
    for ln in open(path, errors="ignore"):
        if '"tool_use"' not in ln and '"usage"' not in ln:
            continue
        try:
            e = json.loads(ln)
        except Exception:
            continue
        msg = e.get("message", {})
        u = msg.get("usage")
        if u:
            tot += (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0))
        for c in (msg.get("content") or []) if isinstance(msg.get("content"), list) else []:
            if (c.get("type") == "tool_use" and c.get("name") == "Write"
                    and str(c.get("input", {}).get("file_path", "")).endswith("response.md")):
                rp = c["input"]["file_path"]
    return (rp, tot) if rp else None


def main():
    if len(sys.argv) < 2:
        print("usage: persist_token_usage.py <workflow_transcript_dir> [more...]")
        sys.exit(1)
    by_path = {}  # response_path -> (skilldir, model, total)  (dedupe by output path)
    for d in sys.argv[1:]:
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            res = scan_transcript(f)
            if not res:
                continue
            rp, tot = res
            if "/runs/" not in rp:
                continue
            parts = rp.split("/runs/")[1].split("/")
            skilldir, eval_id = parts[0], parts[1]
            if eval_id not in CORE:
                continue
            run_dir = os.path.dirname(rp)
            mp = os.path.join(run_dir, "run_metadata.json")
            m = json.loads(open(mp).read()) if os.path.exists(mp) else {}
            if m.get("tooling", "disabled") != "disabled":
                continue
            if m.get("pass") == 2 or os.path.basename(run_dir).endswith("D"):
                continue
            by_path[rp] = (skilldir, m.get("model", "unknown"), tot)

    agg = defaultdict(lambda: {"sum_total": 0, "n": 0})
    for rp, (sd, model, tot) in by_path.items():
        k = f"{sd}|{model}"
        agg[k]["sum_total"] += tot
        agg[k]["n"] += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(agg, indent=2))
    print(f"Wrote {OUT} with {len(agg)} (skill|model) groups:")
    for k, v in sorted(agg.items(), key=lambda x: -x[1]["sum_total"]):
        avg = v["sum_total"] / v["n"] if v["n"] else 0
        print(f"  {k:<50} n={v['n']:>2}  avg/audit={avg:>10,.0f}")


if __name__ == "__main__":
    main()
