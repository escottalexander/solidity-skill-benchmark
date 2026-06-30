# Solidity Skill Benchmark — Findings & Hard Facts

A single reference for everything this benchmark has measured, with exact
numbers and the caveats that matter. For how the pipeline works, see
`CLAUDE.md`. For the design of the tooling dimension, see
`docs/superpowers/specs/2026-06-29-tooling-dimension-design.md`.

Last updated: 2026-06-30. Status: preliminary. All runs are single-pass,
source-only (no compiler/tools) unless a section says otherwise.

---

## TL;DR

- **The biggest finding: no single skill significantly beats no skill.** Against a
  raw-model baseline (no methodology), not one of the 6 skills is significantly
  better on recall, on either model. The best skill ties the baseline; some
  skills are *worse* than baseline and all add more false positives. (§8)
- **Of the skills, `ethskills/audit` leads.** Highest recall on both Sonnet and
  Opus, and the only skill statistically clear of the bottom of the pack on
  both — but still only a tie with the no-skill baseline.
- **A strict 1–6 ranking is not real.** On macro per-eval F1 the six skills are
  a statistical tie (overlapping 95% CIs); the order even reshuffled between a
  5-eval pilot and the full 27. Only pooled per-finding (micro) analysis
  separates a top from a bottom.
- **The model matters more than the skill.** Opus beats Sonnet on every skill,
  decisively (pooled McNemar z=6.95). Opus's *worst* skill ties Sonnet's *best*.
- **Running the same audit twice catches ~40% more bugs** (16.2% → 22.7% recall),
  purely from run-to-run variance.
- **Real static-analysis tools (Slither/Foundry) did NOT significantly help**
  (pooled z=0.67, a tie) — even though 100% of tool-enabled agents actually ran
  them.
- **Precision is low: 15–35% depending on model.** Most flagged issues are not
  known bugs. This is a triage aid, not an auditor.
- **The winning skill is also the leanest** — best recall on the smallest skill
  (a single 3 KB file) at the lowest token cost.

---

## 1. What was tested

- **Eval set:** `evals/core_subset.json` — 27 curated cases (the `vfp_*`
  directories) drawn from FORGE-Curated published professional audit reports.
  **167 ground-truth findings** total across the 27 (avg 6.2/eval, range 1–32),
  severity mix High 49 / Medium 105 / Critical 13.
- **Skills (6 full auditors, head-to-head comparable):** `scv-scan`,
  `ethskills/audit`, `ethskills/security`, `pashov-skills/solidity-auditor`,
  `sc-auditor/security-auditor`, `qs_skills/behavioral-state-analysis`. (The
  other ~14 enabled skills are narrow single-category or non-enumeration skills
  and are excluded from the headline board — see CLAUDE.md "Skill
  Comparability".)
- **Models:** Claude Sonnet 4.6 and Opus 4.8.
- **Grading:** an LLM grader checks each ground-truth finding against the audit
  response (generous on wording, strict on substance), and counts substantive
  findings not in ground truth as false positives.

## 2. Metrics & methodology notes

- **Recall** = known bugs caught / total known bugs. **Precision** = caught /
  (caught + false positives). **F1** = harmonic mean.
- **Micro vs macro matters.** *Macro* recall averages the 27 per-eval recalls
  (each eval weighted equally); *micro* pools all 167 findings then divides
  (each finding weighted equally). Micro is the trustworthy ranking signal —
  per-eval scores swing 0–100% and have too little power.
- **Why macro-F1 can't rank these:** with n=27 the 95% CIs are ~±9% and overlap
  for all six skills; paired t-tests find no separable pairs. The headline
  ranking therefore uses **micro-recall + a paired per-finding McNemar test**
  (`scripts/rank_analysis.py`, `scripts/model_compare.py`).
- **Precision penalizes real-but-unlisted findings.** A "false positive" is any
  substantive flag not in the answer key — some are genuine bugs the original
  audit missed, some are noise. Applied equally to all skills, so *relative*
  ranking holds, but absolute precision reads low.

## 3. Skill ranking (the hard numbers)

Micro-recall (found / 167) per skill, both models, source-only single pass:

| Skill | Sonnet recall | Sonnet prec | Opus recall | Opus prec |
|---|---|---|---|---|
| ethskills/audit | **20.4%** (34) | 18.8% | **31.1%** (52) | 30.1% |
| ethskills/security | 15.0% (25) | 16.0% | 28.7% (48) | 30.8% |
| pashov/solidity-auditor | 18.0% (30) | 18.8% | 25.1% (42) | 35.9% |
| sc-auditor/security-auditor | 16.8% (28) | 19.7% | 24.6% (41) | 28.9% |
| scv-scan | 12.6% (21) | 21.2% | 22.8% (38) | 36.5% |
| qs-bsa | 13.2% (22) | 18.5% | 20.4% (34) | 26.0% |

**Tiered verdict (statistically defensible):**
- **Top: `ethskills/audit`** — #1 micro-recall on both models; within-model
  paired-McNemar separable from the bottom of the pack on both.
- **Middle (a tie):** pashov, sc-auditor, ethskills/security.
- **Bottom:** scv-scan, qs-bsa.
- On *macro-F1* the whole board is a tie and the order differs from micro
  (e.g. sc-auditor tops Sonnet macro-F1 but is mid-pack on micro-recall). Do not
  quote a strict 1–6 order. (At 5 evals the pilot's macro-F1 leader was pashov;
  at 27 evals ethskills/audit leads micro-recall — the reshuffle that proves
  small benchmarks mislead.)

**Within-model separable pairs** (paired per-finding McNemar, |z|>1.96 — the only
statistically real gaps; everything else is a tie):
- *Sonnet (4 of 15 pairs):* eth/audit > scv-scan (z=2.60); eth/audit > eth/security
  (z=2.06); eth/audit > qs-bsa (z=2.45); pashov > scv-scan (z=1.96).
- *Opus (5 of 15 pairs):* eth/audit > scv-scan (z=2.47); eth/audit > sc-auditor
  (z=2.04); eth/audit > qs-bsa (z=3.53); eth/security > scv-scan (z=2.04);
  eth/security > qs-bsa (z=2.33).
- eth/audit is the only skill statistically ahead of others on **both** models.

## 4. Model effect: Sonnet vs Opus

Paired per-finding (same 167 findings × 6 skills = 1,002 finding-checks):

- Both found: 114 · **Opus-only: 141** · **Sonnet-only: 46** · both missed: 701.
- Opus won the disagreements **141 to 46** → pooled **McNemar z=6.95** (Opus
  significantly better). Every individual skill is also significant (z 2.19–3.68).
- Opus's worst skill (qs-bsa, 20.4%) ties Sonnet's best (eth/audit, 20.4%).
- **The 141 vs 46 is the *disagreement* set, not "Opus strictly better."** Each
  model catches real bugs the other misses → a single pass is noisy (motivates §5).

## 5. Multi-pass effect (same model, same skill, run twice)

Two identical Sonnet/no-tools passes over the 27 evals, merged (a bug counts if
*either* pass caught it). `scripts/multipass_analysis.py`:

| | recall |
|---|---|
| Single pass (avg of pass 1, pass 2) | 16.2% |
| Two passes, merged (union) | **22.7%** |
| Lift | **+6.4 pts ≈ 40% more bugs** |

Consistent across all 6 skills (+5.1 to +7.5 pts). Pass 1 (16.0%) ≈ pass 2
(16.5%), so the gain is pure variance capture, not one pass being better.
**Caveat:** the union also accumulates both passes' false positives — recall up,
precision down.

## 6. Tooling A/B: does Slither/Foundry help?

Because the core_subset contracts are partial snapshots that mostly don't
compile (only ~2–3 of 27), the tooling A/B runs on a **separate 23-eval
compilable set** built from the 300 (`evals/tooling_set.json`; 23 of 26
candidates compiled). Sonnet, 6 skills, tools-off vs tools-on, same evals.
`scripts/tooling_compare.py`.

- **100% of tool-enabled agents actually ran Slither AND forge** (verified by
  transcript scan), so the comparison is valid. Halmos went unused (nobody wrote
  a fuzz harness); Mythril could not be installed on Python 3.14 (so the suite
  was Slither + Halmos + Foundry).
- Per-skill recall lift (tools off → on, same 23 evals), none significant:

  | Skill | off | on | lift |
  |---|---|---|---|
  | scv-scan | 37.8% | 45.9% | +8.1% |
  | sc-auditor | 43.2% | 48.6% | +5.4% |
  | qs-bsa | 35.1% | 40.5% | +5.4% |
  | ethskills/security | 43.2% | 43.2% | 0.0% |
  | ethskills/audit | 48.6% | 45.9% | −2.7% |
  | pashov | 51.4% | 45.9% | −5.4% |
- **Pooled: tools caught +20 findings source-only missed, source-only caught
  +16 tools missed → z=0.67, a statistical TIE.**
- Likely cause: Slither flags pattern bugs (reentrancy, unchecked calls) a
  capable LLM already finds by reading, while the ground-truth findings are
  mostly logic/business-logic bugs Slither doesn't model.

> ⚠️ The aggregate leaderboard's tools-on rows look far higher than tools-off,
> but that is an artifact: the "off" rows pool core_subset (harder) with the
> compilable set (easier). The **paired** `tooling_compare.py` on identical
> evals is authoritative, and it says tie.

## 7. Token / context-window usage per skill

Reconstructed from agent transcripts (`scripts/token_usage.py`), per audit
averaged over 27 evals. "peak" = high-water mark of context the model held in a
single turn; "total" = input+cache+output summed across turns (cost proxy).

| Skill | Sonnet peak / total | Opus peak / total | skill size |
|---|---|---|---|
| pashov | 61.4K / 606K | 80.9K / **1.23M** | 22 files / 159 KB |
| scv-scan | 60.4K / **953K** | 65.8K / 995K | 68 files / 198 KB |
| sc-auditor | 54.5K / 427K | 63.6K / 643K | 25 files / 268 KB |
| ethskills/security | 50.6K / 378K | 55.5K / 486K | 1 file / 19 KB |
| qs-bsa | 44.9K / 329K | 50.4K / 542K | 3 files / 9 KB |
| **ethskills/audit** | 46.6K / **347K** | 48.8K / **444K** | 1 file / 3 KB |

- **Peak context window usage is fairly uniform (45–81K)** — agents read skill
  bundles selectively, so a 68-file skill doesn't fill the window proportionally.
- **Total token cost varies ~3×** within a model (scv-scan/pashov heaviest,
  ethskills/audit & qs-bsa lightest), driven by turns/files the methodology
  touches, not window size.
- **Opus costs ~1.3–2× more than Sonnet** per audit (more reasoning), but the
  *same* skills are heaviest and lightest on both models — the cost profile is a
  property of the skill, not the model.
- **The winner is the leanest on both models:** ethskills/audit = best recall,
  smallest skill (3 KB), lowest cost. More skill machinery did not buy accuracy.
- On the tooling A/B's compilable evals (smaller, single-file contracts), peak
  context was lower (32–44K) — an eval-size effect, not a tooling effect.
- `total` includes cheap cache reads, so it overstates dollar cost but is fair
  as a relative measure. (Tokens reconstructed from transcripts; not persisted
  in `run_metadata` — see §11.)

**Tokens per real finding** (a cost-efficiency metric now shown on the
leaderboard = total tokens over the 27 evals ÷ real findings caught; lower is
cheaper to surface a known bug): **baseline is the cheapest** (~214K/finding
Sonnet, ~241K Opus) and ethskills/audit is close (~231K Opus); **scv-scan is the
worst by far** (~2.15M/finding Sonnet — heavy *and* low-recall). So the no-skill
baseline and the lean winner are also the most token-efficient; the heaviest
skills cost up to ~10× more per bug found. (Persisted via
`scripts/persist_token_usage.py` → `results/token_usage.json`.)

## 8. Baseline: how much do the skills add over the raw model?

No-skill control — the raw model audits the same 27 evals with no methodology,
Sonnet and Opus (`scripts/setup_baseline.py`; analysis `scripts/baseline_compare.py`).

**Headline: no skill significantly beats just asking the model.** Paired
per-finding McNemar of each skill vs the no-skill baseline, on the same 27 evals:

| Sonnet | recall | precision | vs baseline |
|---|---|---|---|
| ethskills/audit | 20.4% | 18.8% | tie (z=0.60) |
| **baseline (no skill)** | **18.6%** | **24.6%** | — |
| pashov | 18.0% | 18.8% | tie |
| sc-auditor | 16.8% | 19.7% | tie |
| ethskills/security | 15.0% | 16.0% | tie |
| qs-bsa | 13.2% | 18.5% | tie |
| scv-scan | 12.6% | 21.2% | **WORSE (z=2.04)** |

| Opus | recall | precision | vs baseline |
|---|---|---|---|
| ethskills/audit | 31.1% | 30.1% | tie (z=1.22) |
| ethskills/security | 28.9% | 30.8% | tie |
| **baseline (no skill)** | **26.9%** | **44.6%** | — |
| pashov | 25.1% | 35.9% | tie |
| sc-auditor | 24.6% | 28.9% | tie |
| scv-scan | 22.8% | 36.5% | tie |
| qs-bsa | 20.4% | 26.0% | **WORSE (z=2.04)** |

- **On both models, zero skills beat baseline at a significant level.** The best
  skill (ethskills/audit) is a statistical tie with no skill at all.
- **One skill is significantly *worse* than baseline on each model** (scv-scan on
  Sonnet, qs-bsa on Opus) — the methodology actively hurt.
- **Baseline precision beats every skill** (24.6% vs 15–21% on Sonnet; 44.6% vs
  26–36% on Opus). The skills add false positives without adding recall.
- Net: on this benchmark, these Solidity audit skills do not meaningfully
  outperform simply asking the model to audit. ethskills/audit is the best *of
  the skills*, but "best skill" ≈ "no skill" here.
- Baseline caught 31/167 findings on Sonnet, 45/167 on Opus.

## 9. Caveats & limitations

- **Low precision (15–35%).** Most flags are not known bugs; heavy human triage
  required. This is the single biggest limiter on real-world usefulness.
- **Partial snapshots.** Eval contracts are the audited files only, with
  unresolved imports — they don't compile, which is why the default arm is
  source-only and the tooling arm needed a separate compilable set.
- **Single pass, n=27.** Preliminary. Adjacent skills are often within noise.
- **LLM grader.** Matching is model-judged; generous-on-wording / strict-on-
  substance, but not a human auditor.
- **Cost not in USD.** Token counts are recorded; no per-token price split, so
  the leaderboard's cost column stays blank.

## 10. Reproducing the numbers

| Script | Produces |
|---|---|
| `scripts/aggregate.py` | Headline leaderboard: 6 skills + baseline × 2 models on core_subset, source-only, ranked by **micro-recall** → `results/benchmark.json`, `site/data.json`. (Tooling A/B + multi-pass are excluded here by design; use their own scripts.) |
| `scripts/rank_analysis.py` | Per-model CI + paired-McNemar skill ranking (`RANK_MODEL`, `TOOLING` env filters) |
| `scripts/model_compare.py` | Sonnet-vs-Opus micro-recall + paired McNemar |
| `scripts/multipass_analysis.py` | Single-pass vs 2-pass union recall (the +40%) |
| `scripts/tooling_compare.py` | Tools-on vs tools-off lift on the compilable set (`MODEL` env) |
| `scripts/baseline_compare.py` | Each skill vs the no-skill baseline, per model (paired McNemar) |
| `scripts/token_usage.py <workflow_dir>` | Per-skill token / context-window usage (ad-hoc) |
| `scripts/persist_token_usage.py <dirs>` | Writes `results/token_usage.json` (headline-run token totals) so aggregate can show tokens-per-finding |
| `scripts/compile_eval.py` / `discover_compilable.py` | Build harness + the compilable set |
| `scripts/setup_*.py` | One-cell-per-file run setup for each experiment |

Eval set: `evals/core_subset.json` (skills) and `evals/tooling_set.json`
(compilable). Raw runs live under `results/runs/<skill>/<eval>/<timestamp>/`
(gitignored).

## 11. Data provenance & scale

**816 graded audits** on disk (each = one audit + one grading), Sonnet 4.6 and
Opus 4.8, all source-only single pass unless noted. Run timestamps map to
experiments as follows (navigate `results/runs/<skill>/<eval>/<timestamp>/`):

| Timestamp prefix | Experiment | Cells |
|---|---|---|
| `20260627T110953`, `20260627T113545` | Sonnet skill leaderboard (pass 1) | 162 |
| `20260628T001622` | Opus skill leaderboard | 162 |
| `20260629T114219…D` / `…E` | Tooling A/B — tools-off (D) / tools-on (E), 23 compilable evals | 138 / 138 |
| `20260630T004431…P2` | Sonnet pass 2 (multi-pass study) | 162 |
| `20260630T122555…Bsonnet` / `…Bopus` | No-skill baseline | 27 / 27 |

Per-run identity (`model`, `tooling`, `is_baseline`, `pass`) lives in each run's
`run_metadata.json`; the analysis scripts select on those fields, so re-running
any script reproduces the corresponding table above. Tokens were not persisted
per run (only one early run has them); `token_usage.py` reconstructs them from
the agent transcripts under the session's `subagents/workflows/` directory.
