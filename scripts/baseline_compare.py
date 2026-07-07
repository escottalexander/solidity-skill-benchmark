#!/usr/bin/env python3
"""Skill-vs-baseline: does any audit skill beat simply asking the raw model?

For each model, ranks the 6 skills plus the no-skill baseline by micro-recall on
the 27 core_subset evals, and runs a paired per-finding McNemar test of each
skill against baseline. Also prints micro-precision so the false-positive cost
is visible.

Usage: python3 scripts/baseline_compare.py
"""
import json
import os
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_select as rsel

PROJ = Path(__file__).resolve().parent.parent
CORE = [e["eval_id"] for e in json.loads(
    (PROJ / "evals" / "core_subset.json").read_text())["evals"]]
SKILLS = ["ethskills__audit", "ethskills__security", "pashov-skills__solidity-auditor",
          "sc-auditor__security-auditor", "scv-scan", "qs_skills__behavioral-state-analysis"]
SHORT = {"ethskills__audit": "eth/audit", "ethskills__security": "eth/security",
         "pashov-skills__solidity-auditor": "pashov", "sc-auditor__security-auditor": "sc-auditor",
         "scv-scan": "scv-scan", "qs_skills__behavioral-state-analysis": "qs-bsa"}
MODELS = [("claude-sonnet-4-6", "SONNET"), ("claude-opus-4-8", "OPUS")]


def fmap(sk, ev, model):
    """Per-finding verdicts for a cell (majority across reps; run selection via
    run_select — EXPERIMENTS env for manifest mode, legacy heuristics else)."""
    return rsel.majority_fmap(rsel.cell_gradings(sk, ev, model=model))


def fp_of(sk, model):
    fp = 0.0
    for ev in CORE:
        gs = rsel.cell_gradings(sk, ev, model=model)
        if gs:
            fp += rsel.mean_summary(gs)["false_positives"]
    return fp


def main():
    for model, label in MODELS:
        bmap = {}
        for ev in CORE:
            for k, v in fmap("baseline", ev, model).items():
                bmap[(ev, k)] = v
        bfound, btot, bfp = sum(bmap.values()), len(bmap), fp_of("baseline", model)
        bprec = bfound / (bfound + bfp) if (bfound + bfp) else 0
        rows = [("baseline", bfound, btot, bprec, None, None)]
        for sk in SKILLS:
            sm = {}
            for ev in CORE:
                for k, v in fmap(sk, ev, model).items():
                    sm[(ev, k)] = v
            keys = [k for k in sm if k in bmap]
            if not keys:
                continue
            found, tot = sum(sm[k] for k in keys), len(keys)
            b01 = sum(1 for k in keys if not bmap[k] and sm[k])
            b10 = sum(1 for k in keys if bmap[k] and not sm[k])
            z = abs(b01 - b10) / math.sqrt(b01 + b10) if (b01 + b10) else 0
            fp = fp_of(sk, model)
            prec = found / (found + fp) if (found + fp) else 0
            rows.append((SHORT[sk], found, tot, prec, z, (b01, b10)))
        rows.sort(key=lambda r: -(r[1] / r[2] if r[2] else 0))
        print(f"=== {label}: skill vs no-skill baseline (27 evals, paired McNemar) ===")
        print(f"{'':<13}{'recall':>13}{'precision':>11}{'vs baseline':>22}")
        for name, found, tot, prec, z, disc in rows:
            if z is None:
                verdict = "<== NO SKILL"
            elif z > 1.96 and disc[0] > disc[1]:
                verdict = f"BEATS (z={z:.2f})"
            elif z > 1.96 and disc[1] > disc[0]:
                verdict = f"WORSE (z={z:.2f})"
            else:
                verdict = f"tie (z={z:.2f})"
            print(f"  {name:<11}{found:>4}/{tot} = {found/tot:>5.1%}{prec:>11.1%}{verdict:>22}")
        print()


if __name__ == "__main__":
    main()
