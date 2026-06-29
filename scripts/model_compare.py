#!/usr/bin/env python3
"""Compare two models on the same skills/evals using per-finding outcomes.

Reports, for each model: micro-averaged recall (found/total findings) per skill
with Wilson 95% CIs, ranked. Then a paired per-finding McNemar test (sonnet vs
opus) per skill, which answers "did switching models significantly change what
got caught," controlling for which findings are hard."""
import json, os, math

PROJ = "/Users/elliott/dev/solidity-skill-benchmark"
SKILLS = ["scv-scan", "ethskills__audit", "ethskills__security",
          "pashov-skills__solidity-auditor", "sc-auditor__security-auditor",
          "qs_skills__behavioral-state-analysis"]
SHORT = {"scv-scan": "scv-scan", "ethskills__audit": "eth/audit",
         "ethskills__security": "eth/security", "pashov-skills__solidity-auditor": "pashov",
         "sc-auditor__security-auditor": "sc-auditor", "qs_skills__behavioral-state-analysis": "qs-bsa"}
CORE = [e["eval_id"] for e in json.load(open(f"{PROJ}/evals/core_subset.json"))["evals"]]
MODELS = {"sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}

def grading_for(sk, ev, model_id):
    d = f"{PROJ}/results/runs/{sk}/{ev}"
    if not os.path.isdir(d): return None
    for run in sorted(os.listdir(d), reverse=True):
        gp = os.path.join(d, run, "grading.json")
        if not os.path.exists(gp): continue
        try: g = json.load(open(gp))
        except: continue
        m = g.get("run_metadata", {}).get("model")
        if not m:
            mf = os.path.join(d, run, "run_metadata.json")
            if os.path.exists(mf):
                try: m = json.load(open(mf)).get("model")
                except: m = None
        if m == model_id: return g
    return None

def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (c-h, c+h)

# per (model, skill): map (eval,fid)->found, and total FP
found = {m: {} for m in MODELS}
fp = {m: {} for m in MODELS}
for mk, mid in MODELS.items():
    for sk in SKILLS:
        fmap = {}; tfp = 0
        for ev in CORE:
            g = grading_for(sk, ev, mid)
            if g is None: continue
            for f in g["findings"]: fmap[(ev, f["id"])] = bool(f["found"])
            tfp += g["summary"].get("false_positives", 0)
        found[mk][sk] = fmap; fp[mk][sk] = tfp

T = len(found["sonnet"][SKILLS[0]])  # total findings (same set both models)

for mk in MODELS:
    print(f"\n{'='*70}\nMICRO-RECALL — {mk} ({MODELS[mk]})\n{'='*70}")
    rows = []
    for sk in SKILLS:
        k = sum(found[mk][sk].values()); lo, hi = wilson(k, T)
        mp = k/(k+fp[mk][sk]) if (k+fp[mk][sk]) else 0
        rows.append((sk, k, k/T, lo, hi, mp, fp[mk][sk]))
    rows.sort(key=lambda x: -x[2])
    print(f"{'skill':<13}{'recall':>16}{'95% CI':>16}{'micro-prec':>12}{'FP':>6}")
    for sk, k, r, lo, hi, mp, f in rows:
        print(f"{SHORT[sk]:<13}{k:>3}/{T} = {r:>5.1%}   [{lo:>5.1%},{hi:>5.1%}]{mp:>11.1%}{f:>6}")

for mk in MODELS:
    print(f"\n{'='*70}\nWITHIN-{mk} separability (paired McNemar over findings, |z|>1.96)\n{'='*70}")
    sep = 0
    for a in range(len(SKILLS)):
        for b in range(a + 1, len(SKILLS)):
            A, B = SKILLS[a], SKILLS[b]
            keys = found[mk][A].keys()
            b01 = sum(1 for k in keys if not found[mk][A][k] and found[mk][B].get(k))
            b10 = sum(1 for k in keys if found[mk][A][k] and not found[mk][B].get(k))
            nd = b01 + b10
            if nd == 0: continue
            z = abs(b10 - b01) / math.sqrt(nd)
            if z > 1.96:
                hi, lo = (SHORT[A], SHORT[B]) if b10 > b01 else (SHORT[B], SHORT[A])
                print(f"  {hi:>12} > {lo:<12} z={z:.2f}"); sep += 1
    print(f"  separable pairs: {sep}/15  (rest are ties)")

print(f"\n{'='*70}\nPAIRED sonnet -> opus, per skill (McNemar on {T} findings)\n{'='*70}")
print("b01 = opus caught that sonnet missed; b10 = sonnet caught that opus missed")
for sk in SKILLS:
    keys = found["sonnet"][sk].keys()
    b01 = sum(1 for kk in keys if not found["sonnet"][sk][kk] and found["opus"][sk].get(kk))
    b10 = sum(1 for kk in keys if found["sonnet"][sk][kk] and not found["opus"][sk].get(kk))
    nd = b01 + b10
    z = abs(b01 - b10)/math.sqrt(nd) if nd else 0
    verdict = "opus SIG better" if (z > 1.96 and b01 > b10) else ("sonnet sig better" if (z > 1.96 and b10 > b01) else "tie")
    print(f"  {SHORT[sk]:<12} opus+{b01:>3}  sonnet+{b10:>3}  z={z:>4.2f}  {verdict}")

# pooled across all skills
b01 = sum(1 for sk in SKILLS for kk in found["sonnet"][sk] if not found["sonnet"][sk][kk] and found["opus"][sk].get(kk))
b10 = sum(1 for sk in SKILLS for kk in found["sonnet"][sk] if found["sonnet"][sk][kk] and not found["opus"][sk].get(kk))
z = abs(b01-b10)/math.sqrt(b01+b10)
print(f"\n  POOLED (all 6 skills): opus caught +{b01}, sonnet caught +{b10}, z={z:.2f} -> {'opus SIG better' if z>1.96 and b01>b10 else 'tie'}")
