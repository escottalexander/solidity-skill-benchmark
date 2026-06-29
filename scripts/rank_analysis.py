#!/usr/bin/env python3
"""Ranking-confidence analysis for the 6 full-auditor skills over the core_subset.

Restricts to core_subset evals only (so every skill is scored on the SAME set).
Reports per-skill mean F1/recall/precision with t-based 95% CI, and a PAIRED
separability matrix (eval-difficulty cancels out). Also ranks excluding the
noisy single-finding evals.
"""
import json, os, math
from statistics import mean, stdev

PROJ = "/Users/elliott/dev/solidity-skill-benchmark"
SKILLS = ["pashov-skills__solidity-auditor", "sc-auditor__security-auditor", "ethskills__audit",
          "qs_skills__behavioral-state-analysis", "ethskills__security", "scv-scan"]
SHORT = {"pashov-skills__solidity-auditor": "pashov", "sc-auditor__security-auditor": "sc-auditor",
         "ethskills__audit": "eth/audit", "qs_skills__behavioral-state-analysis": "qs-bsa",
         "ethskills__security": "eth/security", "scv-scan": "scv-scan"}
CORE = [e["eval_id"] for e in json.load(open(f"{PROJ}/evals/core_subset.json"))["evals"]]
NFIND = {e: len(json.load(open(f"{PROJ}/evals/{e}/findings.json"))) for e in CORE}
T95 = {4: 2.776, 9: 2.262, 14: 2.145, 19: 2.093, 21: 2.080, 24: 2.064, 26: 2.056}  # df -> t

MODEL = os.environ.get("RANK_MODEL")  # e.g. claude-opus-4-8; None = latest of any model

def latest_grading(sk, ev):
    d = f"{PROJ}/results/runs/{sk}/{ev}"
    if not os.path.isdir(d): return None
    for run in sorted(os.listdir(d), reverse=True):
        gp = os.path.join(d, run, "grading.json")
        if not os.path.exists(gp): continue
        try: g = json.load(open(gp))
        except: continue
        if MODEL:
            m = g.get("run_metadata", {}).get("model")
            if not m:
                mf = os.path.join(d, run, "run_metadata.json")
                if os.path.exists(mf):
                    try: m = json.load(open(mf)).get("model")
                    except: m = None
            if m != MODEL: continue
        return g
    return None

def f1(r, p): return 0.0 if (r + p) == 0 else 2 * r * p / (r + p)

def tcrit(df): return T95.get(df, 2.05)

def collect(evals):
    data = {}
    for sk in SKILLS:
        cells = {}
        for ev in evals:
            g = latest_grading(sk, ev)
            if g is None: continue
            s = g["summary"]
            cells[ev] = (s["recall"], s["precision"], f1(s["recall"], s["precision"]))
        data[sk] = cells
    return data

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
    # paired separability vs each lower-ranked skill
    print("\nPaired separability (same evals; |t|>~2.06 at df~26 => p<0.05):")
    for a in range(len(rows)):
        for b in range(a + 1, len(rows)):
            ska, skb = rows[a][0], rows[b][0]
            common = [e for e in evals if e in data[ska] and e in data[skb]]
            diffs = [data[ska][e][2] - data[skb][e][2] for e in common]
            if len(diffs) < 2: continue
            md = mean(diffs); sd = stdev(diffs); se = sd / math.sqrt(len(diffs))
            t = md / se if se > 0 else float("inf")
            if abs(t) > tcrit(len(diffs) - 1):
                print(f"  {SHORT[ska]:>12} > {SHORT[skb]:<12}  diff={md:+.3f} t={t:+.2f}  SEPARABLE")
    print("  (pairs not listed are statistical ties)")
    return rows

report("ALL core_subset evals", CORE)
report("Excluding single-finding evals (>=2 findings)", [e for e in CORE if NFIND[e] >= 2])
