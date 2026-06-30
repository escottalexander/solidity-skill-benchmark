#!/usr/bin/env python3
"""Multi-pass effect: how much more does running the SAME skill+model twice and
merging the results catch, vs a single pass.

For each (skill, eval) in core_subset, reads the original Sonnet/no-tools run
(pass 1) and the repeat run (pass 2, tagged pass=2). Per ground-truth finding it
records whether each pass caught it, then reports, pooled and per-skill:
  - mean single-pass recall
  - union-of-2 recall (caught in pass 1 OR pass 2)
  - the lift (union - mean single)

Usage: python3 scripts/multipass_analysis.py
"""
import json
import os
import math
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-4-6"
SKILLS = ["scv-scan", "ethskills__audit", "ethskills__security",
          "pashov-skills__solidity-auditor", "sc-auditor__security-auditor",
          "qs_skills__behavioral-state-analysis"]
SHORT = {"scv-scan": "scv-scan", "ethskills__audit": "eth/audit",
         "ethskills__security": "eth/security", "pashov-skills__solidity-auditor": "pashov",
         "sc-auditor__security-auditor": "sc-auditor",
         "qs_skills__behavioral-state-analysis": "qs-bsa"}
CORE = [e["eval_id"] for e in json.loads(
    (PROJ / "evals" / "core_subset.json").read_text())["evals"]]


def _meta(run_dir):
    mp = run_dir / "run_metadata.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            return {}
    return {}


def grading(sk, ev, which):
    """which=1 original core_subset run (ts 20260627*), which=2 the pass=2 run."""
    d = PROJ / "results" / "runs" / sk / ev
    if not d.is_dir():
        return None
    runs = sorted([r for r in d.iterdir() if r.is_dir()], reverse=True)
    for r in runs:
        gp = r / "grading.json"
        if not gp.exists():
            continue
        m = _meta(r)
        if m.get("model") != MODEL or m.get("tooling", "disabled") != "disabled":
            continue
        if which == 2 and m.get("pass") != 2:
            continue
        if which == 1 and (m.get("pass") == 2 or not r.name.startswith("20260627")):
            continue
        try:
            return json.loads(gp.read_text())
        except Exception:
            continue
    return None


def main():
    print(f"Multi-pass effect (model={MODEL}, source-only, {len(CORE)} core_subset evals)\n")
    # per skill accumulate finding-level found1/found2
    rows = []
    pooled = {"n": 0, "p1": 0, "p2": 0, "union": 0}
    for sk in SKILLS:
        n = p1 = p2 = union = 0
        missing = 0
        for ev in CORE:
            g1, g2 = grading(sk, ev, 1), grading(sk, ev, 2)
            if g1 is None or g2 is None:
                missing += 1
                continue
            f1 = {f["id"]: bool(f["found"]) for f in g1["findings"]}
            f2 = {f["id"]: bool(f["found"]) for f in g2["findings"]}
            for fid in f1:
                n += 1
                a, b = f1[fid], f2.get(fid, False)
                p1 += a
                p2 += b
                union += (a or b)
        rows.append((sk, n, p1, p2, union, missing))
        pooled["n"] += n
        pooled["p1"] += p1
        pooled["p2"] += p2
        pooled["union"] += union

    print(f"{'skill':<13}{'pass1':>9}{'pass2':>9}{'mean-1':>9}"
          f"{'2-pass∪':>10}{'lift':>8}{'miss':>6}")
    print("-" * 64)
    for sk, n, p1, p2, union, missing in rows:
        if n == 0:
            print(f"{SHORT[sk]:<13}  (no paired data yet){'  miss='+str(missing)}")
            continue
        r1, r2, ru = p1 / n, p2 / n, union / n
        mean1 = (r1 + r2) / 2
        print(f"{SHORT[sk]:<13}{r1:>9.1%}{r2:>9.1%}{mean1:>9.1%}"
              f"{ru:>10.1%}{ru - mean1:>+8.1%}{missing:>6}")

    n = pooled["n"]
    if n:
        r1, r2, ru = pooled["p1"] / n, pooled["p2"] / n, pooled["union"] / n
        mean1 = (r1 + r2) / 2
        print("-" * 64)
        print(f"{'POOLED':<13}{r1:>9.1%}{r2:>9.1%}{mean1:>9.1%}{ru:>10.1%}{ru - mean1:>+8.1%}")
        print(f"\nOne pass catches ~{mean1:.1%} of known bugs on average; "
              f"two passes merged catch {ru:.1%}.")
        print(f"That's a +{ru - mean1:.1%} absolute lift "
              f"({(ru/mean1 - 1)*100:.0f}% more bugs) from a second pass.")
        # how many NEW bugs the 2nd pass adds beyond pass 1 alone
        # (union - pass1) / pass1
        if pooled["p1"]:
            add = (pooled["union"] - pooled["p1"]) / pooled["p1"] * 100
            print(f"Relative to a single fixed run, adding a 2nd pass found "
                  f"{add:.0f}% more bugs.")
    else:
        print("\nNo paired pass-1/pass-2 data yet — let pass 2 finish.")


if __name__ == "__main__":
    main()
