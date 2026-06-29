#!/usr/bin/env python3
"""Tooling A/B: per skill, compare tools-enabled vs tools-disabled on the same
compilable eval set, for a fixed model. Reports micro-averaged recall (with
Wilson CIs), a paired per-finding McNemar test (the tooling lift), and which
tools each enabled run actually invoked.

Usage: MODEL=claude-sonnet-4-6 python3 scripts/tooling_compare.py
"""
import json
import os
import math
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
SKILLS = ["scv-scan", "ethskills__audit", "ethskills__security",
          "pashov-skills__solidity-auditor", "sc-auditor__security-auditor",
          "qs_skills__behavioral-state-analysis"]
SHORT = {"scv-scan": "scv-scan", "ethskills__audit": "eth/audit",
         "ethskills__security": "eth/security", "pashov-skills__solidity-auditor": "pashov",
         "sc-auditor__security-auditor": "sc-auditor",
         "qs_skills__behavioral-state-analysis": "qs-bsa"}
TSET = json.loads((PROJ / "evals" / "tooling_set.json").read_text())["evals"]


def grading_for(sk, ev, tooling):
    d = PROJ / "results" / "runs" / sk / ev
    if not d.is_dir():
        return None
    for run in sorted(os.listdir(d), reverse=True):
        gp = d / run / "grading.json"
        if not gp.exists():
            continue
        try:
            g = json.loads(gp.read_text())
        except Exception:
            continue
        rm = g.get("run_metadata", {})
        if rm.get("model") != MODEL:
            continue
        if rm.get("tooling", "disabled") != tooling:
            continue
        return g, rm
    return None


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def collect(tooling):
    found, fp, tools = {}, {}, {}
    for sk in SKILLS:
        fmap, tfp, tset = {}, 0, set()
        for ev in TSET:
            r = grading_for(sk, ev, tooling)
            if r is None:
                continue
            g, rm = r
            for f in g["findings"]:
                fmap[(ev, f["id"])] = bool(f["found"])
            tfp += g["summary"].get("false_positives", 0)
            tset.update(rm.get("tools_invoked", []))
        found[sk], fp[sk], tools[sk] = fmap, tfp, tset
    return found, fp, tools


def main():
    print(f"Tooling A/B  (model={MODEL}, {len(TSET)} compilable evals)\n")
    dis_f, dis_fp, _ = collect("disabled")
    en_f, en_fp, en_tools = collect("enabled")

    # common findings present in both arms
    print(f"{'skill':<13}{'recall off':>14}{'recall ON':>14}{'lift':>8}"
          f"{'McNemar':>20}{'tools used':>22}")
    print("-" * 92)
    for sk in SKILLS:
        keys = sorted(set(dis_f[sk]) & set(en_f[sk]))
        if not keys:
            print(f"{SHORT[sk]:<13}  (no paired data yet)")
            continue
        T = len(keys)
        ko = sum(dis_f[sk][k] for k in keys)
        ke = sum(en_f[sk][k] for k in keys)
        b01 = sum(1 for k in keys if not dis_f[sk][k] and en_f[sk][k])  # tools caught, off missed
        b10 = sum(1 for k in keys if dis_f[sk][k] and not en_f[sk][k])  # off caught, tools missed
        nd = b01 + b10
        z = abs(b01 - b10) / math.sqrt(nd) if nd else 0
        verdict = "tools SIG +" if (z > 1.96 and b01 > b10) else (
            "tools SIG -" if (z > 1.96 and b10 > b01) else "tie")
        tools_used = ",".join(sorted(en_tools[sk])) or "none"
        print(f"{SHORT[sk]:<13}{ko}/{T}={ko/T:>7.1%}{ke}/{T}={ke/T:>7.1%}"
              f"{(ke-ko)/T:>+8.1%}{f'+{b01}/-{b10} z={z:.2f}':>20}{tools_used:>22}")

    # pooled
    pk = [(sk, k) for sk in SKILLS for k in (set(dis_f[sk]) & set(en_f[sk]))]
    b01 = sum(1 for sk, k in pk if not dis_f[sk][k] and en_f[sk][k])
    b10 = sum(1 for sk, k in pk if dis_f[sk][k] and not en_f[sk][k])
    if b01 + b10:
        z = abs(b01 - b10) / math.sqrt(b01 + b10)
        print(f"\nPOOLED: tools caught +{b01}, source-only caught +{b10}, "
              f"z={z:.2f} -> {'tools SIG better' if z > 1.96 and b01 > b10 else 'tie'}")
    else:
        print("\nNo paired enabled/disabled data yet — run both arms first.")


if __name__ == "__main__":
    main()
