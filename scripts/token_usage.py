#!/usr/bin/env python3
"""Reconstruct per-skill token / context-window usage from workflow agent
transcripts (run_metadata didn't persist tokens for workflow runs).

For each agent transcript (.jsonl) it sums usage and classifies the agent as an
auditor (wrote response.md) or grader (wrote grading.json), and maps it to a
skill via the run-dir path it wrote. Reports, per skill (auditors):
  - peak context: the high-water mark of (input + cache_read + cache_creation)
    in a single turn = how full the context window got
  - output tokens: how much the model wrote (reasoning + report)
  - total billed: input+output+cache summed across turns (overall cost proxy)
Plus the skill's static on-disk footprint (SKILL.md + bundled files).

Usage: python3 scripts/token_usage.py <workflow_transcript_dir>
"""
import json
import os
import sys
import glob
from collections import defaultdict
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SKILL_DIRS = {  # run-dir name -> skill dir on disk (for static footprint)
    "scv-scan": "skills/scv-scan",
    "ethskills__audit": "skills/ethskills/audit",
    "ethskills__security": "skills/ethskills/security",
    "pashov-skills__solidity-auditor": "skills/pashov-skills/solidity-auditor",
    "sc-auditor__security-auditor": "skills/sc-auditor/skills/security-auditor",
    "qs_skills__behavioral-state-analysis":
        "skills/qs_skills/plugins/behavioral-state-analysis/skills/behavioral-state-analysis",
}


def agent_stats(path):
    """Return (skilldir, kind, peak_ctx, output, total) for one transcript."""
    peak = output = total = 0
    skilldir = kind = None
    for ln in open(path, errors="ignore"):
        try:
            e = json.loads(ln)
        except Exception:
            continue
        msg = e.get("message", {})
        u = msg.get("usage")
        if u:
            inp = u.get("input_tokens", 0)
            cr = u.get("cache_read_input_tokens", 0)
            cc = u.get("cache_creation_input_tokens", 0)
            out = u.get("output_tokens", 0)
            peak = max(peak, inp + cr + cc)
            output += out
            total += inp + cr + cc + out
        for c in (msg.get("content") or []) if isinstance(msg.get("content"), list) else []:
            if c.get("type") == "tool_use" and c.get("name") == "Write":
                fp = str(c.get("input", {}).get("file_path", ""))
                if "/runs/" in fp and (fp.endswith("response.md") or fp.endswith("grading.json")):
                    parts = fp.split("/runs/")[1].split("/")
                    skilldir = parts[0]
                    kind = "audit" if fp.endswith("response.md") else "grade"
    return skilldir, kind, peak, output, total


def static_footprint(skilldir):
    d = PROJ / SKILL_DIRS.get(skilldir, "")
    if not d.exists():
        return 0, 0
    files = [f for f in d.rglob("*") if f.is_file()]
    nbytes = sum(f.stat().st_size for f in files)
    return len(files), nbytes


def main():
    if len(sys.argv) < 2:
        print("usage: token_usage.py <workflow_transcript_dir>")
        sys.exit(1)
    tdir = sys.argv[1]
    by_skill = defaultdict(lambda: {"n": 0, "peak": [], "out": [], "tot": []})
    for f in glob.glob(os.path.join(tdir, "*.jsonl")):
        sd, kind, peak, out, tot = agent_stats(f)
        if kind != "audit" or not sd:
            continue
        s = by_skill[sd]
        s["n"] += 1
        s["peak"].append(peak)
        s["out"].append(out)
        s["tot"].append(tot)

    def avg(x):
        return sum(x) / len(x) if x else 0

    rows = [(sd, v["n"], avg(v["peak"]), avg(v["out"]), avg(v["tot"]))
            for sd, v in by_skill.items()]
    rows.sort(key=lambda r: -r[2])  # by peak context
    print("Per-skill AUDITOR token usage (averaged over evals)\n")
    print(f"{'skill':<34}{'n':>4}{'peak ctx':>11}{'output':>9}{'total':>10}"
          f"{'skill files':>12}{'skill KB':>10}")
    print("-" * 90)
    for sd, n, peak, out, tot in rows:
        nf, nb = static_footprint(sd)
        print(f"{sd:<34}{n:>4}{peak:>11,.0f}{out:>9,.0f}{tot:>10,.0f}"
              f"{nf:>12}{nb/1024:>9.0f}K")


if __name__ == "__main__":
    main()
