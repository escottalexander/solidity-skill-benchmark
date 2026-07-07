# Solidity Skill Benchmark — Findings & Hard Facts

A single reference for everything this benchmark has measured, with exact
numbers, the precise configuration that produced them, and the caveats that
matter. For how the pipeline works day-to-day, see `CLAUDE.md`.

Last updated: 2026-07-06.
Models: auditors are **Sonnet 4.6** (`claude-sonnet-4-6`), **Opus 4.8**
(`claude-opus-4-8`), and **Sonnet 5** (`claude-sonnet-5`, added §13); grader is
Sonnet 4.6 throughout. (See the `sonnet`-alias note in §1.1.)
Status: the **current headline** (§3–§6) is from the hardened pipeline re-run of
2026-07-05/06 — frozen versioned prompts, ≥1-rep-with-CIs, every cell validated,
0 validation issues (1579 graded runs on disk incl. the Sonnet 5 board, §13).
Older experiments that have not
been re-run on the new pipeline (multi-pass §7, tooling A/B §8, token usage §9)
are from the **pre-overhaul corpus** (archived to
`results/archive_pre_overhaul_20260705.tar.gz`) and are labelled as such.

---

## TL;DR

- **No skill beats "just ask the model."** Against a raw-model baseline (no
  methodology), not one of the 6 audit skills is significantly better on recall,
  on either model. On Opus, three skills are significantly *worse* than no skill
  at all. (§4)
- **Of the skills, `ethskills/audit` leads** — #1 micro-recall on both models
  (Sonnet 19.4%, Opus 29.3%) and the leanest skill (one 4 KB file). But "best
  skill" ≈ "no skill" here: it only ties the baseline.
- **The scores are NOT training-data memorization.** Renaming every
  contract/file/identifier and stripping all comments (the "canary" test) did
  not lower recall for any group (pooled McNemar z=−1.39, a tie). Confirmed by a
  fresh set of post-cutoff audits where recall did not collapse. This is the
  single most important robustness result. (§6)
- **The model matters far more than the skill.** Model ranking on this task is
  **Opus 4.8 > Sonnet 5 > Sonnet 4.6** (Sonnet 5 > 4.6: pooled McNemar z=3.43;
  Opus > Sonnet 5: z=2.62). Opus 4.8's *worst* skill ≈ Sonnet 4.6's *best*.
  (§5, §13)
- **On Sonnet 5, one skill finally beats "no skill".** `ethskills/security`
  significantly beats the no-skill baseline on Sonnet 5 (z=2.36) — the only
  skill to beat baseline on any model. On 4.6/Opus, no skill did. (§13)
- **Precision is low (16–37%).** Most flagged issues are not known bugs. This is
  a triage aid, not an auditor.
- **A strict 1–7 ranking is not real.** After Holm-Bonferroni correction only a
  handful of pairwise gaps survive, all on Opus and all involving eth/audit or
  eth/security beating the bottom of the pack. (§3)
- **Pre-overhaul, still-informative:** a second identical pass catches ~40% more
  bugs (pure run-to-run variance, §7); real static-analysis tools
  (Slither/Foundry) did not significantly help (§8).

---

## 1. Exact benchmark configuration

Everything below is recorded per run in `run_metadata.json` and is selectable by
the analysis scripts. Nothing here is reconstructed from memory.

### 1.1 Models

| Role | Model ID | Notes |
|---|---|---|
| Auditor (Sonnet runs) | `claude-sonnet-4-6` | Sonnet 4.6 |
| Auditor (Opus runs) | `claude-opus-4-8` | Opus 4.8 |
| Auditor (Sonnet 5 runs) | `claude-sonnet-5` | added 2026-07-06 (§13) |
| Grader (ALL runs) | `claude-sonnet-4-6` | the grader is always Sonnet 4.6, even when grading Opus audits, so grading is held constant across the model comparison |

> **On the `sonnet` alias (2026-07-06).** The 4.6/Opus/canary/fresh runs were
> executed via the `sonnet`/`opus` Workflow aliases *before* the main instance
> was reloaded to pick up the Claude 5 family; at that time `sonnet` resolved to
> `claude-sonnet-4-6`. After the reload the `sonnet` alias resolves to
> `claude-sonnet-5` (verified by probing subagents on both the Agent-tool and
> Workflow paths). The Sonnet 5 board (§13) was run *after* the reload, so its
> `sonnet`-alias runs are genuinely `claude-sonnet-5`. Model tags are recorded
> per run in `run_metadata.json` and are correct as of the run date.

Subagents are general-purpose (full tool access: Read/Grep/Glob/Bash/Write).
Source-only runs are told the tools are unavailable; tooling runs get the
security toolchain on PATH (§8).

### 1.2 Eval sets

| Set (`evals/<name>.json`) | N | Findings | Provenance |
|---|---|---|---|
| `core_subset` (`vfp_*`) | 27 | 167 (C 13 / H 49 / M 105) | FORGE-Curated — published professional audit reports, pre-cutoff |
| `canary_set` (`vfp_*_cn`) | 27 | 167 | core_subset with comments stripped + contracts/files/imports renamed (`scripts/make_canary.py`); findings renamed consistently so grading still works |
| `fresh_set` (`fr_*`) | 3 | 24 | audits published AFTER model cutoffs (post-2026-03), imported as compiling pinned repos (`scripts/import_recent_audit.py`) — cannot be in training data |
| `tooling_set` | 23 | — | subset of the 300 that compiles via the scaffold harness; used only for the tooling A/B (§8) |

Per-eval layout: `contracts/` (Solidity source shown to the auditor),
`findings.json` (ground truth, never shown), `metadata.json`. Fresh evals also
carry `project_lock.json` (repo URL + pinned commit + submodule pins) so a
compiling project can be rebuilt for tooling runs.

### 1.3 Skills (6 full auditors, head-to-head comparable)

| Skill | SKILL.md path | Size |
|---|---|---|
| `ethskills/audit` | `skills/ethskills/audit/SKILL.md` | 1 file, 4 KB |
| `ethskills/security` | `skills/ethskills/security/SKILL.md` | 1 file, 20 KB |
| `scv-scan` | `skills/scv-scan/SKILL.md` | 68 files, 348 KB |
| `pashov-skills/solidity-auditor` | `skills/pashov-skills/solidity-auditor/SKILL.md` | 22 files, 204 KB |
| `sc-auditor/security-auditor` | `skills/sc-auditor/skills/security-auditor/SKILL.md` | multi-file bundle |
| `qs_skills/behavioral-state-analysis` | `skills/qs_skills/plugins/.../behavioral-state-analysis/SKILL.md` | 3-file bundle |

The `baseline` "skill" is the no-methodology control: the raw model audits the
same contracts with no SKILL.md in its workspace. The other ~14 enabled skills
are narrow single-category or non-enumeration skills and are excluded from the
headline board (see CLAUDE.md "Skill Comparability").

### 1.4 Prompts (frozen, versioned)

Every subagent prompt is rendered from a literal template in `agents/prompts/`
by `scripts/prepare_run.py` (via `scripts/render_prompt.py`), saved into the run
dir as `prompt.md` / `grader_prompt.md`, and stamped with a version
`<file>@<sha256[:12]>` in `run_metadata.json`. Editing a template changes its
hash, so any two runs are provably prompt-identical iff their versions match.

**Auditor prompt** (`auditor_source.md` / `auditor_source_baseline.md`) tells the
subagent its workspace path, points it at `skill/SKILL.md` (omitted for
baseline), lists the in-scope contracts, and asks for a finding list with
Title / Severity / Description / Location / Recommendation, "real exploitable
vulnerabilities, not gas/style." It states the source-only environment
constraint (imports unresolved, no compiler, tools not installed) and requires
the report be written to `response.md`.

**Grader prompt** (`grader.md`) reads `findings.json` + `response.md`, and for
EACH ground-truth finding decides found/not-found ("generous on wording, strict
on substance"; a vague category mention doesn't count). It also enumerates every
substantive (C/H/M) response finding that matches no ground-truth finding as an
itemized false positive. It writes `grading.json` with a per-finding array
(exactly one entry per ground-truth id, in order), `false_positive_details[]`,
and a `summary`. The template injects the exact finding count + id list to stop
graders renumbering non-contiguous ids (the bug that corrupted 10 pre-overhaul
cells, §11).

**Exact template versions per experiment** (this is the precise prompt each
result used):

| Experiment | Auditor version | Baseline-auditor version | Grader version |
|---|---|---|---|
| `full-sonnet-a`, `full-sonnet-b`, `full-opus` | `auditor_source.md@2dff46521684` | `auditor_source_baseline.md@89c9a3e630a6` | `grader.md@efb50eb88f88` |
| `canary-sonnet`, `fresh-sonnet` | `auditor_source.md@0216c256904b` | `auditor_source_baseline.md@2bd99d985b44` | `grader.md@efb50eb88f88` |

The only difference between the two auditor versions is a guard added after the
"hallucinated audit" incident (§11): the newer template makes the agent verify
its input files exist and write an explicit `ERROR` line instead of auditing
from memory. On a valid workspace the audit task is identical. The grader
template is the same (`@efb50eb88f88`) across every experiment in this doc.

### 1.5 Repetitions, aggregation, statistics

- **Reps:** Sonnet headline = 3 reps/cell; Opus headline = 1 rep/cell; canary =
  1 rep; fresh = 3 reps. (`prepare_run.py --reps N`.)
- **Micro vs macro:** *micro*-recall pools all 167 findings then divides (each
  finding weighted equally); *macro* averages the 27 per-eval recalls. Micro is
  the ranking signal — per-eval scores swing 0–100% and macro CIs (~±9% at n=27)
  overlap for everyone. The leaderboard reports micro-recall as the rep-mean,
  with a bootstrap 95% CI resampling *evals* (clusters, seed 42).
- **Significance:** paired **per-finding McNemar** on the same (skill, eval,
  finding) triples, **Holm-Bonferroni corrected** across the 15 (or 21) pairwise
  tests per model (`scripts/rank_analysis.py`). For multi-rep cells the tests use
  majority-vote per finding (found iff caught in ≥half the reps), so their
  internal recall can differ from the leaderboard's rep-mean by ≤2 pts.
- **Grading held constant:** same grader model and grader template across all
  experiments, so recall differences are auditor/skill/eval effects, not grading
  drift.

### 1.6 Experiment manifest (the current corpus)

| Experiment | Model | Eval set | Reps | Cells | Purpose |
|---|---|---|---|---|---|
| `full-sonnet-a` | Sonnet | core_subset | 3 | 324 | headline (4 skills) |
| `full-sonnet-b` | Sonnet | core_subset | 3 | 243 | headline (2 skills + baseline) |
| `full-opus` | Opus | core_subset | 1 | 189 | headline (6 skills + baseline) |
| `canary-sonnet` | Sonnet | canary_set | 1 | 189 | contamination test |
| `fresh-sonnet` | Sonnet | fresh_set | 3 | 63 | contamination-free set |

Each manifest lives at `results/experiments/<name>.json` and lists every cell;
the analysis scripts select runs by manifest, not by directory-name heuristics.
**1012 graded runs total** on disk (the 5 experiments above + a 4-cell gate
test), all validated clean.

## 2. Metrics

- **Recall** = known bugs caught / total known bugs. **Precision** = caught /
  (caught + false positives). **F1** = harmonic mean.
- A "false positive" is any substantive (C/H/M) flag not in the answer key —
  some are genuine bugs the original audit missed, some are noise. Applied
  equally to all skills, so *relative* precision ranking holds, but absolute
  precision reads low.

## 3. Headline: skill ranking (current, hardened pipeline)

Micro-recall (rep-mean, found / 167), bootstrap 95% CI over evals; auditors are
**Opus 4.8** and **Sonnet 4.6**, grader is Sonnet 4.6. (Sonnet 5 board in §13.)
Published to `results/benchmark.json` / `site/data.json`.

| Skill | Opus recall [95% CI] | Opus prec | Sonnet recall [95% CI] | Sonnet prec |
|---|---|---|---|---|
| **ethskills/audit** | **29.3%** [21,41] | 23.4% | **19.4%** [12,30] | 16.7% |
| ethskills/security | 26.4% [17,40] | 21.1% | 17.2% [10,27] | 17.8% |
| sc-auditor/security-auditor | 24.6% [15,38] | 24.9% | 17.6% [10,29] | 17.5% |
| pashov/solidity-auditor | 20.4% [12,31] | 26.4% | 16.0% [9,26] | 16.1% |
| qs-bsa | 18.0% [12,26] | 19.9% | 15.4% [9,24] | 17.7% |
| scv-scan | 18.0% [10,28] | 26.8% | 12.8% [7,21] | 23.6% |
| *baseline (no skill)* | *28.7%* [20,43] | *24.5%* | *17.4%* [10,28] | *17.4%* |

**Separable pairs after Holm-Bonferroni** (`scripts/rank_analysis.py`; the only
statistically real gaps — everything else is a tie):

- *Opus (3 pairs):* eth/audit > qs-bsa (z=3.41, p_holm=0.010); eth/audit >
  scv-scan (z=3.31, p_holm=0.013); eth/audit > pashov (z=3.13, p_holm=0.023).
- *Sonnet:* **no pair survives correction.** eth/audit is #1 but not separable
  from the pack at n=27/167.

Do not quote a strict 1–7 order: adjacent skills are within noise, and macro-F1
(which weights evals equally) reshuffles the order entirely and separates
nobody.

## 4. Skills vs the no-skill baseline

Paired per-finding McNemar of each skill vs the raw-model baseline on the same 27
evals (`scripts/baseline_compare.py`; recall shown is that script's
majority-vote figure, ≤2 pts from the §3 leaderboard):

| Sonnet | recall | prec | vs baseline |
|---|---|---|---|
| ethskills/security | 17.4% | 18.0% | tie (z=1.07) |
| ethskills/audit | 16.8% | 14.8% | tie (z=0.73) |
| qs-bsa | 15.6% | 17.9% | tie |
| **baseline** | **15.0%** | **15.3%** | — |
| pashov | 15.0% | 15.2% | tie |
| sc-auditor | 15.0% | 15.3% | tie |
| scv-scan | 12.6% | 23.3% | tie (z=0.94) |

| Opus | recall | prec | vs baseline |
|---|---|---|---|
| ethskills/audit | 29.3% | 23.4% | tie (z=0.20) |
| **baseline** | **28.7%** | **24.5%** | — |
| ethskills/security | 26.3% | 21.2% | tie (z=0.78) |
| sc-auditor | 24.6% | 24.8% | tie (z=1.40) |
| pashov | 20.4% | 26.4% | **WORSE (z=2.40)** |
| scv-scan | 18.0% | 26.8% | **WORSE (z=3.29)** |
| qs-bsa | 18.0% | 19.9% | **WORSE (z=3.67)** |

- **On both models, zero skills significantly beat baseline.** The best skill
  (eth/audit) is a statistical tie with no skill at all.
- **On Opus, three skills are significantly *worse* than baseline** — the
  methodology actively subtracts value on the stronger model.
- Net: on this benchmark these Solidity audit skills do not meaningfully
  outperform simply asking the model to audit.

## 5. Model effect: Opus 4.8 vs Sonnet 4.6

Paired per-finding across all 6 skills (`scripts/model_compare.py`; Sonnet 4.6 =
3-rep majority, Opus 4.8 = 1 rep):

- **Opus 4.8 caught +127** findings Sonnet 4.6 missed vs **+53** the other way →
  pooled **McNemar z=5.52** (Opus 4.8 significantly better). eth/audit,
  eth/security, and sc-auditor are individually significant.
- Opus 4.8's worst skill ≈ Sonnet 4.6's best skill. The model choice dominates
  the skill choice.
- For how Sonnet 5 compares, see §13 (added 2026-07-06).

## 6. Contamination test — the scores are NOT memorization

The vfp_ evals come from PUBLISHED audits, so a standing worry was that recall
reflects the model having seen the report in training. Two independent checks,
both on the hardened pipeline.

**Canary test (the direct one).** `evals/canary_set.json` mirrors the 27 core
evals with all comments stripped and every contract/file/import name renamed
(findings renamed consistently). Same model (Sonnet), same 167 findings, audited
identifiers gone. `scripts/canary_compare.py` pairs each canary against its
original per finding (all 7 groups, 189/189 graded, 0 issues):

| Skill | orig recall | canary recall | Δ | verdict |
|---|---|---|---|---|
| ethskills/audit | 16.8% | 20.4% | +3.6 | tie (z=−1.34) |
| ethskills/security | 17.4% | 16.8% | −0.6 | tie |
| pashov | 15.0% | 18.0% | +3.0 | tie |
| sc-auditor | 15.0% | 18.0% | +3.0 | tie |
| scv-scan | 12.6% | 11.4% | −1.2 | tie |
| qs-bsa | 15.6% | 15.0% | −0.6 | tie |
| baseline | 15.0% | 17.4% | +2.4 | tie |
| **POOLED** | | | | **tie, z=−1.39** |

**Stripping the memorization keys did not lower recall for any group** — pooled,
canaries caught 74 findings the originals missed vs 58 the other way (z=−1.39,
canaries marginally higher, not significant). The benchmark measures auditing
ability, not training-data recall. *Caveat:* originals are 3-rep majority vs
1-rep canaries; a single rep should if anything score *lower* (fewer attempts)
and doesn't, which only strengthens the read.

**Fresh post-cutoff evals (the corroborating one).** `evals/fresh_set.json` — 3
audits published after the model cutoffs (Tenbin/Zellic, Alt Fun/Guardian,
Spiral Stake V2/Cyfrin), imported as compiling pinned repos, 24 findings.
`fresh-sonnet` (7 groups × 3 reps, 63/63 graded):

| Skill | recall | prec |
|---|---|---|
| ethskills/audit | 16.7% | 26.7% |
| pashov | 13.9% | 24.4% |
| baseline | 12.5% | 22.5% |
| sc-auditor | 12.5% | 24.3% |
| scv-scan | 12.5% | 39.1% |
| ethskills/security | 9.7% | 19.4% |
| qs-bsa | 9.7% | 20.6% |

Same shape as the vfp_ Sonnet board (eth/audit #1, baseline mid-pack, no skill
running away) and **recall did NOT collapse** (10–17% vs the vfp_ board's
13–19%). Memorization-driven scores would crater on truly unseen code; they
don't. *Caveat:* only 3 evals / 24 findings, so 95% CIs are very wide — this
corroborates the canary result rather than standing alone. 13 more vetted
post-cutoff candidates are staged in `docs/fresh_audit_candidates.json` to grow
this into a fresh-only headline with real power.

## 7. Multi-pass effect (PRE-OVERHAUL corpus, archived)

Two identical Sonnet/no-tools passes over the 27 evals, merged (a bug counts if
*either* pass caught it), `scripts/multipass_analysis.py`:

| | recall |
|---|---|
| Single pass (avg of pass 1, pass 2) | 16.2% |
| Two passes, merged (union) | **22.7%** |
| Lift | **+6.4 pts ≈ 40% more bugs** |

Consistent across all 6 skills (+5.1 to +7.5 pts); pass 1 ≈ pass 2, so the gain
is pure run-to-run variance capture. Caveat: the union also accumulates both
passes' false positives (recall up, precision down). This motivated the ≥3-rep
default in the new pipeline; it has not itself been re-run on the hardened
pipeline.

## 8. Tooling A/B: does Slither/Foundry help? (PRE-OVERHAUL corpus, archived)

Because core_subset contracts mostly don't compile, this ran on the separate
23-eval compilable `tooling_set`, Sonnet, 6 skills, tools-off vs tools-on, same
evals (`scripts/tooling_compare.py`).

- **100% of tool-enabled agents actually ran Slither AND forge** (transcript-
  verified), so the comparison is valid. Halmos went unused (no fuzz harness
  written); Mythril could not be installed on Python 3.14.
- Per-skill recall lift (off → on), none significant: scv-scan +8.1, sc-auditor
  +5.4, qs-bsa +5.4, eth/security 0.0, eth/audit −2.7, pashov −5.4.
- **Pooled: tools caught +20 findings source-only missed, source-only caught +16
  tools missed → z=0.67, a statistical TIE.**
- Likely cause: Slither flags pattern bugs a capable LLM already finds by
  reading, while the ground-truth findings are mostly business-logic bugs
  Slither doesn't model.

> The toolchain is now fully installed and verified for a re-run on the hardened
> pipeline (forge/cast/slither/semgrep/aderyn/echidna/medusa/halmos/solhint), and
> the fresh evals compile as real pinned projects — a paired tools-on/off re-run
> on those is the natural next experiment.

## 9. Token / context usage per skill (PRE-OVERHAUL corpus, archived)

Reconstructed from the archived agent transcripts (`scripts/token_usage.py`),
per audit averaged over 27 evals. "peak" = high-water context in a single turn;
"total" = input+cache+output across turns (cost proxy).

| Skill | Sonnet peak / total | Opus peak / total | skill size |
|---|---|---|---|
| pashov | 61.4K / 606K | 80.9K / **1.23M** | 22 files / 159 KB |
| scv-scan | 60.4K / **953K** | 65.8K / 995K | 68 files / 198 KB |
| sc-auditor | 54.5K / 427K | 63.6K / 643K | 25 files / 268 KB |
| ethskills/security | 50.6K / 378K | 55.5K / 486K | 1 file / 19 KB |
| qs-bsa | 44.9K / 329K | 50.4K / 542K | 3 files / 9 KB |
| **ethskills/audit** | 46.6K / **347K** | 48.8K / **444K** | 1 file / 3 KB |

- Peak context is fairly uniform (45–81K): agents read skill bundles
  selectively, so a 68-file skill doesn't fill the window proportionally.
- Total token cost varies ~3× within a model, driven by turns/files touched, not
  window size; Opus costs ~1.3–2× Sonnet per audit; the same skills are heaviest
  and lightest on both models.
- **The winner is the leanest:** eth/audit = best recall, smallest skill (4 KB),
  lowest cost. More skill machinery did not buy accuracy.

**Post-overhaul boards (added 2026-07-07).** The current 3-model leaderboard
carries token columns again: `scripts/backfill_tokens.py` reconstructs each
run's auditor total from the workflow transcripts and writes it into the run's
metadata; `aggregate.py` derives tok/audit and tok/find from those per-run
values. Where a cell was re-run, the recorded tokens are those of the attempt
whose report was actually graded (the latest `response.md` writer) — retry
waste isn't charged to the skill. Coverage: 1312/1323 board runs (11 Sonnet 5
runs have no surviving transcript). Two observations from the restored
numbers: per-audit cost rises with model strength (baseline: 195K on
Sonnet 4.6 → 332K on Opus 4.8 → 516K on Sonnet 5 — Sonnet 5 spends 2–5× more
tokens per audit than 4.6 across skills), and pashov is the heaviest skill on
every model (3.1M/audit on Sonnet 5) while the eth skills stay mid-cost at the
top of the recall board.

## 10. Caveats & limitations

- **Low precision (16–37%).** Most flags are not known bugs; heavy human triage
  required. The single biggest limiter on real-world usefulness.
- **n is small.** 27 evals / 167 findings for the vfp_ board; only 3 evals for
  the fresh set. Adjacent skills are often within noise — trust the tiered
  conclusions, not exact ranks.
- **Opus headline is 1-rep.** Given §7's variance, the Opus board is noisier than
  the 3-rep Sonnet board; treat Opus per-skill recall as ±a few points.
- **LLM grader.** Matching is Sonnet-judged (generous-on-wording /
  strict-on-substance), not a human auditor. Grader reliability/calibration
  harnesses exist (`scripts/grader_reliability.py`, `grader_calibration.py`) but
  the 80-pair human calibration sheet (`results/calibration/labels_todo.json`)
  is not yet labelled, so the grader's own error rate is not yet quantified.
- **Precision penalizes real-but-unlisted findings** — see §2.
- **Cost not in USD.** Token counts recorded; no per-token price split.
- **Auditor-prompt version differs** between the headline board and the
  contamination runs (§1.4) — identical audit task, only the input-verification
  guard differs.

## 11. Pipeline overhaul & data-integrity history (2026-07-04→06)

The pre-2026-07-05 corpus (816 runs) was archived and deleted; the headline was
re-run from scratch on a hardened pipeline. What changed and why:

- **Frozen versioned prompts.** None of the 816 old runs saved its rendered
  prompt, so cross-run prompt identity was unverifiable. Now every run saves
  `prompt.md`/`grader_prompt.md` + template hash (§1.4).
- **Run-integrity validation.** `scripts/validate_runs.py` checks coverage,
  grading schema, finding-count/id match, summary arithmetic, FP itemization,
  and cross-cell contamination. It found 12 of 816 old cells defective: 10 where
  the grader mis-counted findings (root cause: `vfp_00099`/`vfp_00032` have
  non-contiguous ids that baited graders into renumbering — the grader prompt now
  injects the exact id list) and 2 with a grading.json but no response.md
  (phantom 0% recalls). The current corpus validates 100% clean.
- **Multiple-comparison correction.** The old §3 quoted every |z|>1.96 pair; at
  15 tests/model that yields ~1 false positive/model by chance. All pairwise
  claims are now Holm-corrected (§3).
- **Contamination controls added** (§6): canary variants + fresh post-cutoff
  evals.
- **Hallucinated-audit incident (important).** During the Opus re-run, macOS's
  tmp cleaner silently emptied workspaces staged in `/tmp` during a rate-limit
  stall. 88 agents wrote nothing, but **101 agents fabricated plausible audit
  reports purely from the file list in their prompt** — and those hallucinations
  passed every naive integrity check (response present, grading parseable,
  contract names mentioned — the names were in the prompt). They were caught only
  because their recall distribution collapsed vs sibling cells. All 189 Opus
  cells were re-run on verified workspaces. Fixes: workspaces now live in the
  repo cache (never system tmp), and the auditor prompt requires the agent to
  verify inputs and emit an explicit ERROR rather than audit from memory.
  **Lesson: an agent benchmark must treat plausible-looking output as zero
  evidence of real work — only distributional checks against known-good siblings
  caught this.**
- **Reliability under limits.** The re-run survived four separate rate-limit
  walls (spend, session ×2, weekly) purely via workflow resume-from-cache;
  running two large workflows concurrently triggers server-side 529 storms, so
  experiments are serialized.

## 12. Reproducing the numbers

| Script | Produces |
|---|---|
| `scripts/prepare_run.py` | Deterministic experiment prep: workspaces, frozen prompts, manifests, cells |
| `scripts/aggregate.py --experiment <names…>` | Rep-averaged micro-recall board + bootstrap CIs |
| `scripts/rank_analysis.py` | Per-model CI + **Holm-corrected** paired McNemar (`RANK_MODEL`, `EXPERIMENTS`, `TOOLING` env) |
| `scripts/baseline_compare.py` | Each skill vs no-skill baseline, per model (`EXPERIMENTS` env) |
| `scripts/model_compare.py` | Sonnet-vs-Opus micro-recall + paired McNemar |
| `scripts/canary_compare.py` | Contamination test: canary vs original per-finding McNemar |
| `scripts/validate_runs.py --experiment <name>` | Integrity check; lists cells to re-run |
| `scripts/make_canary.py` / `import_recent_audit.py` | Build canary variants / import fresh compilable evals |
| `scripts/multipass_analysis.py` / `tooling_compare.py` | Pre-overhaul multi-pass / tooling A/B (archived corpus) |

Analysis scripts select runs via `EXPERIMENTS=<manifest,…>` (rep-aware) or fall
back to legacy directory heuristics when unset. Raw runs live under
`results/runs/<skill>/<eval>/<timestamp>r<rep>/` (gitignored); manifests and the
published board are committed.

## 13. Sonnet 5 (added 2026-07-07)

After the main instance was reloaded to pick up the Claude 5 family, the
`sonnet` alias resolves to **`claude-sonnet-5`** (see §1.1). The benchmark was
run on Sonnet 5 exactly as for the 4.6 board — 6 skills + baseline × 27
core_subset evals × 3 reps, source-only, frozen prompts (auditor
`auditor_source.md@0216c256904b`, grader `grader.md@efb50eb88f88`).
Experiments `full-sonnet5-a` / `full-sonnet5-b`, 567 graded runs, 0 validation
issues.

Micro-recall (rep-mean, found / 167), bootstrap 95% CI:

| Skill | Sonnet 5 recall [CI] | Sonnet 5 prec | (Sonnet 4.6 recall / prec) |
|---|---|---|---|
| ethskills/security | **23.2%** [14,36] | 33.9% | 17.2% / 17.8% |
| pashov | 21.4% [13,34] | 39.9% | 16.0% / 16.1% |
| ethskills/audit | 21.2% [13,34] | 29.9% | 19.4% / 16.7% |
| sc-auditor | 20.0% [12,33] | 33.0% | 17.6% / 17.5% |
| **baseline (no skill)** | 17.8% [10,30] | 30.3% | 17.4% / 17.4% |
| qs-bsa | 17.0% [10,27] | 29.4% | 15.4% / 17.7% |
| scv-scan | 15.4% [9,26] | 33.1% | 12.8% / 23.6% |

**Findings:**

- **Sonnet 5 is a real improvement over Sonnet 4.6.** Pooled paired per-finding
  McNemar across the 6 skills: Sonnet 5 caught **+88** findings Sonnet 4.6
  missed vs **+48** the other way → **z=+3.43** (Sonnet 5 significantly better).
  Precision also jumps markedly (≈29–40% vs 16–24% on 4.6) — Sonnet 5 finds more
  real bugs *and* flags fewer non-bugs.
- **But Opus 4.8 still beats Sonnet 5.** Pooled McNemar: Opus caught **+101**
  that Sonnet 5 missed vs **+67** the other way → **z=−2.62** (Opus 4.8
  significantly better). So the model ranking on this task is
  **Opus 4.8 > Sonnet 5 > Sonnet 4.6.**
- **A skill beats the no-skill baseline for the first time.** On Sonnet 5,
  `ethskills/security` significantly beats baseline (paired McNemar z=+2.36) —
  the only skill to significantly beat "just ask the model" on ANY model in this
  benchmark. eth/audit, sc-auditor, pashov, qs-bsa tie baseline; scv-scan ties
  (slightly below). So on the stronger Sonnet 5, methodology starts to add value
  where on 4.6/Opus it did not — though it's still one skill out of six.
- **Skill ranking within Sonnet 5 is a tie** after Holm-Bonferroni: no pair
  separable (eth/security > scv-scan is raw-significant only, p_holm=0.16).
- eth/audit is no longer the clear leader on Sonnet 5 — eth/security tops the
  board — another reminder that the skill order is within noise and shifts by
  model (§3, §10).

> **Grader caveat (important for cross-model reads).** The Sonnet 5 board was
> graded by **Sonnet 5** (the only Sonnet reachable post-reload), whereas the
> Sonnet 4.6 and Opus 4.8 boards were graded by **Sonnet 4.6**. So the
> Sonnet-5-vs-4.6 and Sonnet-5-vs-Opus comparisons above blend an
> auditor-model change with a grader-model change — some of the +88/−48 shift
> could be the Sonnet 5 grader judging matches differently. Two things temper
> this: (a) precision *rose* on Sonnet 5, which is not what a uniformly more
> generous grader would produce; (b) the **within-Sonnet-5** skill ranking and
> the eth/security-beats-baseline result use one grader throughout and are
> unaffected. A clean cross-model auditor comparison would require re-grading
> all three boards with a single fixed grader — not yet done.
