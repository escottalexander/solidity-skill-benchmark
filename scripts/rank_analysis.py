#!/usr/bin/env python3
"""Ranking-confidence analysis for the 6 full-auditor skills over the core_subset.

Restricts to core_subset evals only (so every skill is scored on the SAME set).
Reports per-skill mean F1/recall/precision with t-based 95% CI, a PAIRED
macro-F1 separability matrix, and a per-finding paired McNemar matrix on
micro-recall. ALL pairwise tests are Holm-Bonferroni corrected — with 15
pairs per model at alpha=0.05, ~1 uncorrected "significant" pair per model is
expected by pure chance.

Env: RANK_MODEL=claude-opus-4-8  TOOLING=disabled  (filters, as before)
     EXPERIMENTS=full-sonnet[,..]  (select runs via experiment manifests;
     reps are aggregated: mean stats for macro, majority vote per finding)
"""
import json, os, math, sys
from pathlib import Path
from statistics import mean, stdev, NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_select as rsel

PROJ = str(Path(__file__).resolve().parent.parent)
SKILLS = ["pashov-skills__solidity-auditor", "sc-auditor__security-auditor", "ethskills__audit",
          "qs_skills__behavioral-state-analysis", "ethskills__security", "scv-scan"]
SHORT = {"pashov-skills__solidity-auditor": "pashov", "sc-auditor__security-auditor": "sc-auditor",
         "ethskills__audit": "eth/audit", "qs_skills__behavioral-state-analysis": "qs-bsa",
         "ethskills__security": "eth/security", "scv-scan": "scv-scan"}
CORE = [e["eval_id"] for e in json.load(open(f"{PROJ}/evals/core_subset.json"))["evals"]]
NFIND = {e: len(json.load(open(f"{PROJ}/evals/{e}/findings.json"))) for e in CORE}
T95 = {4: 2.776, 9: 2.262, 14: 2.145, 19: 2.093, 21: 2.080, 24: 2.064, 26: 2.056}  # df -> t

MODEL = os.environ.get("RANK_MODEL")      # e.g. claude-opus-4-8; None = any model
TOOLING = os.environ.get("TOOLING")       # "enabled"/"disabled"; None = any

_ND = NormalDist()


def p_two_sided_z(z):
    return 2 * (1 - _ND.cdf(abs(z)))


def holm(pairs_with_p):
    """Holm-Bonferroni: input [(label, p)], output {label: (p, p_adj, sig)}."""
    m = len(pairs_with_p)
    ordered = sorted(pairs_with_p, key=lambda x: x[1])
    out, running_max = {}, 0.0
    for i, (label, p) in enumerate(ordered):
        adj = min(1.0, (m - i) * p)
        running_max = max(running_max, adj)
        out[label] = (p, running_max, running_max < 0.05)
    return out


def f1(r, p): return 0.0 if (r + p) == 0 else 2 * r * p / (r + p)


def tcrit(df): return T95.get(df, 2.05)


def collect(evals):
    data = {}
    for sk in SKILLS:
        cells = {}
        for ev in evals:
            gs = rsel.cell_gradings(sk, ev, model=MODEL,
                                    tooling=TOOLING or "disabled")
            if not gs: continue
            s = rsel.mean_summary(gs)
            cells[ev] = (s["recall"], s["precision"], s["f1"])
        data[sk] = cells
    return data


def collect_fmaps(evals):
    """skill -> {(eval, finding_id): found} for the per-finding McNemar.
    With reps, a finding counts as found if found in >= half the reps."""
    fmaps = {}
    for sk in SKILLS:
        fm = {}
        for ev in evals:
            gs = rsel.cell_gradings(sk, ev, model=MODEL,
                                    tooling=TOOLING or "disabled")
            if not gs: continue
            for fid, v in rsel.majority_fmap(gs).items():
                fm[(ev, fid)] = v
        fmaps[sk] = fm
    return fmaps


def report(title, evals):
    data = collect(evals)
    print("\n" + "=" * 78)
    print(f"{title}  (n={len(evals)} evals)")
    print("=" * 78)
    rows = []
    for sk in SKILLS:
        fs = [v[2] for v in data[sk].values()]
        rs = [v[0] for v in data[sk].values()]
        ps = [v[1] for v in data[sk].values()]
        n = len(fs)
        m = mean(fs); sd = stdev(fs) if n > 1 else 0
        ci = tcrit(n - 1) * sd / math.sqrt(n) if n > 1 else 0
        rows.append((sk, m, ci, mean(rs), mean(ps), n, data[sk]))
    rows.sort(key=lambda x: -x[1])
    print(f"{'rank':<5}{'skill':<14}{'F1':>7}{'95% CI':>16}{'recall':>8}{'prec':>7}{'n':>4}")
    for i, (sk, m, ci, mr, mp, n, _) in enumerate(rows, 1):
        print(f"{i:<5}{SHORT[sk]:<14}{m:>7.1%}   [{m-ci:>5.1%},{m+ci:>5.1%}]{mr:>8.1%}{mp:>7.1%}{n:>4}")

    # ---- paired macro-F1 t-tests, Holm-corrected across all pairs
    print("\nPaired macro-F1 separability (Holm-corrected across all pairs;")
    print("p from normal approx of t — adequate at df>=20):")
    tests, details = [], {}
    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            ska, skb = rows[a][0], rows[b][0]
            common = [e for e in evals if e in data[ska] and e in data[skb]]
            diffs = [data[ska][e][2] - data[skb][e][2] for e in common]
            if len(diffs) < 2: continue
            md = mean(diffs); sd = stdev(diffs); se = sd / math.sqrt(len(diffs))
            t = md / se if se > 0 else float("inf")
            label = f"{SHORT[ska]} > {SHORT[skb]}" if md > 0 else f"{SHORT[skb]} > {SHORT[ska]}"
            tests.append((label, p_two_sided_z(t)))
            details[label] = (md, t)
    adj = holm(tests)
    any_sig = False
    for label, (p, p_adj, sig) in sorted(adj.items(), key=lambda kv: kv[1][1]):
        md, t = details[label]
        if sig:
            any_sig = True
            print(f"  {label:<28} diff={abs(md):+.3f} t={t:+.2f} "
                  f"p={p:.4f} p_holm={p_adj:.4f}  SEPARABLE")
        elif p < 0.05:
            print(f"  {label:<28} diff={abs(md):+.3f} t={t:+.2f} "
                  f"p={p:.4f} p_holm={p_adj:.4f}  raw-sig only (NOT after Holm)")
    if not any_sig:
        print("  no pair separable after Holm correction (macro-F1 is a tie)")

    # ---- per-finding paired McNemar on micro-recall, Holm-corrected
    print("\nPer-finding paired McNemar (micro-recall; Holm-corrected):")
    fmaps = collect_fmaps(evals)
    tests, details = [], {}
    for a in range(len(SKILLS)):
        for b in range(a + 1, len(SKILLS)):
            ska, skb = SKILLS[a], SKILLS[b]
            keys = [k for k in fmaps[ska] if k in fmaps[skb]]
            b01 = sum(1 for k in keys if fmaps[ska][k] and not fmaps[skb][k])
            b10 = sum(1 for k in keys if not fmaps[ska][k] and fmaps[skb][k])
            if b01 + b10 == 0: continue
            z = (b01 - b10) / math.sqrt(b01 + b10)
            label = (f"{SHORT[ska]} > {SHORT[skb]}" if z > 0
                     else f"{SHORT[skb]} > {SHORT[ska]}")
            tests.append((label, p_two_sided_z(z)))
            details[label] = (abs(z), b01, b10, len(keys))
    adj = holm(tests)
    any_sig = False
    for label, (p, p_adj, sig) in sorted(adj.items(), key=lambda kv: kv[1][1]):
        z, b01, b10, nk = details[label]
        tag = ("SEPARABLE" if sig else
               ("raw-sig only (NOT after Holm)" if p < 0.05 else None))
        if tag:
            any_sig = any_sig or sig
            print(f"  {label:<28} z={z:.2f} disc={max(b01,b10)}:{min(b01,b10)} "
                  f"n={nk} p={p:.4f} p_holm={p_adj:.4f}  {tag}")
    if not any_sig:
        print("  no pair separable after Holm correction")
    print("  (pairs not listed are clear ties)")
    return rows


report("ALL core_subset evals", CORE)
report("Excluding single-finding evals (>=2 findings)", [e for e in CORE if NFIND[e] >= 2])
