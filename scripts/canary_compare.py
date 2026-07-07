#!/usr/bin/env python3
"""Contamination test: does stripping memorization keys drop recall?

Pairs each canary eval (vfp_XXXXX_cn: comments stripped, contract/file names
renamed) against its original (vfp_XXXXX) on the SAME model and the SAME 167
findings. If a skill's recall on canaries is much lower than on originals, its
score on the originals was partly memorization of the published audit, not
auditing. If recall holds, contamination is not inflating the number.

The original run is selected from the headline experiments (full-sonnet-a/b by
default); the canary run from the canary experiment. Per-finding paired
McNemar pools all (skill, eval, finding) triples.

Usage:
  python3 scripts/canary_compare.py
  ORIG_EXPERIMENTS=full-sonnet-a,full-sonnet-b CANARY_EXPERIMENT=canary-sonnet \
    MODEL=claude-sonnet-4-6 python3 scripts/canary_compare.py
"""
import json
import math
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
import run_select as rsel  # noqa: E402

MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
ORIG_EXPS = os.environ.get("ORIG_EXPERIMENTS", "full-sonnet-a,full-sonnet-b")
CANARY_EXP = os.environ.get("CANARY_EXPERIMENT", "canary-sonnet")

SKILLS = ["ethskills__audit", "ethskills__security", "pashov-skills__solidity-auditor",
          "sc-auditor__security-auditor", "scv-scan",
          "qs_skills__behavioral-state-analysis", "baseline"]
SHORT = {"ethskills__audit": "eth/audit", "ethskills__security": "eth/security",
         "pashov-skills__solidity-auditor": "pashov", "sc-auditor__security-auditor": "sc-auditor",
         "scv-scan": "scv-scan", "qs_skills__behavioral-state-analysis": "qs-bsa",
         "baseline": "baseline"}


def fmap_from(experiments, sk, ev):
    os.environ["EXPERIMENTS"] = experiments
    import importlib
    importlib.reload(rsel)
    return rsel.majority_fmap(rsel.cell_gradings(sk, ev, model=MODEL))


def main():
    canary_evals = json.loads((PROJ / "evals" / "canary_set.json").read_text())["evals"]
    pairs = [(e, e[:-3]) for e in canary_evals]  # (canary_id, original_id)

    print(f"Contamination test (model={MODEL})")
    print(f"  originals: {ORIG_EXPS}   canaries: {CANARY_EXP}\n")
    print(f"{'skill':<13}{'orig recall':>13}{'canary recall':>15}{'delta':>9}"
          f"{'McNemar':>20}")
    print("-" * 70)
    pooled_o1c0 = pooled_o0c1 = 0
    for sk in SKILLS:
        o_found = c_found = o_tot = c_tot = 0
        s_o1c0 = s_o0c1 = 0
        for cev, oev in pairs:
            om = fmap_from(ORIG_EXPS, sk, oev)
            cm = fmap_from(CANARY_EXP, sk, cev)
            keys = set(om) & set(cm)
            for k in keys:
                o_tot += 1; c_tot += 1
                o_found += om[k]; c_found += cm[k]
                if om[k] and not cm[k]: s_o1c0 += 1
                elif cm[k] and not om[k]: s_o0c1 += 1
        if not o_tot:
            continue
        pooled_o1c0 += s_o1c0; pooled_o0c1 += s_o0c1
        orec, crec = o_found / o_tot, c_found / c_tot
        nd = s_o1c0 + s_o0c1
        z = (s_o1c0 - s_o0c1) / math.sqrt(nd) if nd else 0
        verdict = (f"DROP z={z:.2f}" if z > 1.96 else
                   (f"UP z={abs(z):.2f}" if z < -1.96 else f"tie z={z:.2f}"))
        print(f"{SHORT[sk]:<13}{orec:>12.1%}{crec:>14.1%}{crec-orec:>+9.1%}"
              f"{verdict:>20}")
    nd = pooled_o1c0 + pooled_o0c1
    z = (pooled_o1c0 - pooled_o0c1) / math.sqrt(nd) if nd else 0
    print("-" * 70)
    print(f"POOLED: orig-only caught {pooled_o1c0}, canary-only caught "
          f"{pooled_o0c1}  ->  z={z:.2f}")
    print("  z>1.96 = recall dropped on canaries (memorization signal);")
    print("  tie = stripping identifiers/comments did NOT change recall "
          "(scores are not memorization).")


if __name__ == "__main__":
    main()
