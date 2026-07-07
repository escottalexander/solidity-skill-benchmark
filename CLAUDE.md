# Solidity Skill Benchmark

Benchmarks Claude Code skills for Solidity smart contract security auditing. This agent orchestrates the pipeline — but ALL mechanical steps (workspaces, prompts, run dirs, validation, aggregation) are deterministic scripts. The agent's only job is spawning subagents and reacting to failures.

## Repository Structure

- `evals/` — eval cases, each containing:
  - `contracts/` — Solidity source files to audit
  - `findings.json` — ground truth vulnerabilities (never shown to auditor)
  - `metadata.json` — project info, CWE tags, severity counts
  - `project_lock.json` — (fresh evals only) repo URL + pinned commit + submodule pins, so tooling workspaces rebuild exactly
- `evals/evals.json` — registry of all evals
- `evals/core_subset.json` — curated ~27 diverse legacy evals (`vfp_*`)
- `evals/tooling_set.json` — 23 legacy evals that compile via the scaffold harness
- `evals/canary_set.json` — contamination canaries (`*_cn`): same code/bugs, comments stripped + contract/file names renamed (`scripts/make_canary.py`)
- `evals/fresh_set.json` — post-cutoff evals imported from recent audits (compilable, cannot be in training data)
- `evals/import_specs/` — one spec JSON per fresh-eval import
- `skills/` — Claude Code skills to benchmark (third-party git clones, gitignored; pinned in `skills_lock.json`); `skills.json` — manifest (name → SKILL.md path, `enabled` flag)
- `agents/prompts/` — **THE frozen prompt templates** (auditor_source[_baseline].md, auditor_tooling[_baseline].md, grader.md). `agents/auditor.md` + `agents/grader.md` document how to use them.
- `scripts/` — the deterministic pipeline (see table below)
- `results/` — `runs/`, `experiments/` (manifests + boards), `calibration/`, `history/`, `benchmark.json`
- `site/` — leaderboard HTML (reads `site/data.json`)

## Reproducibility Rules (non-negotiable)

1. **Frozen prompts.** Subagent prompts are NEVER hand-written. `scripts/prepare_run.py` renders `agents/prompts/*.md` (strict placeholder check both ways) and saves `prompt.md` + `grader_prompt.md` into every run dir, with template versions (`<file>@<sha12>`) in `run_metadata.json`. Editing a template changes its version string; two runs are comparable iff versions match.
2. **Deterministic prep.** Workspaces, run dirs, hashes (skill dir + contracts content), manifests, and cell files all come from `prepare_run.py`. It asserts ground truth is absent from every workspace.
3. **Experiment manifests.** Every new run belongs to a named experiment (`results/experiments/<name>.json` lists every cell). Aggregation/analysis selects runs via manifests — never by directory-name heuristics. (Legacy pre-manifest runs keep the old heuristics in the default `aggregate.py` mode; new runs carry `experiment` in metadata and are excluded from that legacy board.)
4. **Repetitions.** Single passes are noise (a 2nd identical pass changed ~40% of catches — FINDINGS.md §5). Default `--reps 3`; rank on rep-averaged micro-recall with the bootstrap 95% CI `aggregate.py` reports.
5. **Validate before believing.** `scripts/validate_runs.py --experiment <name>` after every run wave; re-run only flagged cells. It checks response presence, grading schema, finding-count/id match vs ground truth, summary arithmetic, FP itemization, cross-cell contamination, and prompt provenance.
6. **Multiple comparisons.** Pairwise skill claims must survive Holm-Bonferroni (`scripts/rank_analysis.py` does this automatically). Quote `p_holm`, not raw z.

## Running an Experiment

### Step 1: Prepare (deterministic)

```bash
python3 scripts/prepare_run.py \
  --experiment sonnet-rep3 \
  --skills scv-scan ethskills/audit baseline \
  --eval-set core_subset \
  --model claude-sonnet-4-6 \
  --tooling disabled \
  --reps 3
```

This creates per-cell workspaces + run dirs + rendered prompts, one `cell_<i>.json` per cell under `.cache/experiments/<name>/cells/`, and the manifest. For tooling runs use `--tooling enabled` (see Tooling Runs below). Baseline = the skill name `baseline`.

### Step 2: Spawn auditors (the agent's job)

One auditor subagent per cell, in parallel (background Agents or a Workflow). The subagent prompt is the cell's `auditorBootstrap` string VERBATIM — it just points the agent at the run dir's `prompt.md`. Model = the experiment's model. Subagents write `response.md` directly to the run dir.

After each auditor completes, record from the Agent tool's `<usage>` block into the run's `run_metadata.json`: `duration_seconds` (from `duration_ms`) and `tokens: {"total": <subagent_tokens>}`. (Cost is NOT surfaced; leave `total_cost_usd` at 0.)

### Step 3: Spawn graders

One grader per completed audit, prompt = the cell's `graderBootstrap` verbatim. Use the STRONGEST model available for grading — grader quality gates everything. Grader writes `grading.json` to the run dir; the orchestrator then merges in `run_metadata` (copied from `run_metadata.json`, never trusted from the grader) and `grading_meta` (`{"model": ..., "tokens": {...}}`). If grading.json is missing/unparseable: re-prompt once, else save reply to `grading_error.txt` and leave ungraded.

### Step 4: Validate, re-run holes

```bash
python3 scripts/validate_runs.py --experiment sonnet-rep3
```
Re-run only flagged cells (their cell files still exist), then re-validate.

### Step 5: Aggregate & analyze

```bash
python3 scripts/aggregate.py --experiment sonnet-rep3            # board + CIs
RANK_MODEL=claude-sonnet-4-6 python3 scripts/rank_analysis.py    # Holm-corrected pairs
```
`aggregate.py` with no args reproduces the legacy headline board (site/data.json); `--experiment ... --publish` publishes an experiment board instead.

### Scaled runs via the Workflow tool

For large matrices, a deterministic `Workflow` that pipelines audit→grade per cell beats hand-managing dozens of background Agents. Hard-won rules (a pilot lost 7/29 cells to violating the first one):

- **One cell per file — never "read a shared manifest and take index N".** Subagents reliably grab the wrong index from shared arrays; each subagent reads ONLY its own `cell_<i>.json` (prepare_run.py already emits these).
- **Pre-step owns isolation + setup** — that is `prepare_run.py`. Pass only tiny data (counts, cells dir) to the workflow as `args`; note `args` may arrive as a JSON string (`typeof args === 'string' ? JSON.parse(args) : args`).
- **Subagents write their own outputs** to the absolute paths in their cell file — the orchestrator never re-transcribes reports.
- **Always validate coverage afterward** (`validate_runs.py`) **and re-run holes** via a small recovery pass over the flagged cells only.

## Tooling Runs (compile + real security tools)

The tooling arm answers "do Slither/Foundry/etc. actually help?" — it requires projects that COMPILE and subagents with FULL tool access.

- **Toolchain**: `python3 scripts/check_tooling.py` verifies and version-stamps: forge/cast (Foundry), slither, semgrep, aderyn, echidna, medusa, halmos, crytic-compile, solc-select, solhint (venv: `.venv-tools/`, plus `~/.foundry/bin`, `~/.cargo/bin`, brew). forge + slither are required; versions are recorded into each run's metadata automatically. Mythril/Manticore are NOT installable on Python 3.14 — treat as unavailable.
- **Which evals compile**: legacy `tooling_set.json` evals compile via the scaffold harness (`compile_eval.py`); fresh `fresh_set.json` evals compile as full pinned clones (preferred — real projects, real remappings, and post-cutoff too).
- `prepare_run.py --tooling enabled` builds one compiling template per eval, then per-cell copies with freshly symlinked `lib/` so concurrent tool runs don't clash; a `slither.config.json` scopes analysis to in-scope sources. The rendered prompt lists tool versions and PATH.
- **Paired analysis only**: compare tools-on vs tools-off on IDENTICAL evals (`scripts/tooling_compare.py`); pooling different eval sets is an artifact machine (FINDINGS.md §6 warning).

## Contamination Control (this gates everything)

The `vfp_*` evals derive from PUBLISHED audits — models may have trained on them. Two mitigations, use both:

1. **Canaries**: `evals/canary_set.json` mirrors core_subset with comments stripped and contract/file/import names renamed (findings.json renamed consistently, so grading still works). Run the same skill/model on originals vs canaries; a large recall drop = memorization. Rebuild anytime: `python3 scripts/make_canary.py --set core_subset --register`.
2. **Fresh evals**: audits published AFTER the models' cutoffs cannot be memorized. `evals/import_specs/*.json` + `python3 scripts/import_recent_audit.py --all` clones the audited repo at the pinned commit, requires `forge build` to pass, extracts scope files into `contracts/`, and registers into `fresh_set.json`. Prefer fresh evals for all new headline claims; they also serve the tooling arm.

## Grader Quality Assurance

The LLM grader is the measurement instrument; its error rate bounds every conclusion.

- `grading.json` must itemize false positives (`false_positive_details`, count must match) — enforced by validate_runs.py.
- **Reliability** (same prompt, k gradings): `python3 scripts/grader_reliability.py --prepare --sample 20 --k 3`, spawn the emitted grader cells, then `--report` (percent agreement, pooled Cohen's kappa, FP spread). Run after ANY grader change.
- **Calibration** (vs human labels): `python3 scripts/grader_calibration.py --sample 80` emits `results/calibration/labels_todo.json`; a human fills `human_found`, saves as `labels.json`, then `--report` gives grader accuracy/kappa + disagreements. Leaderboard gaps below the grader's error rate are noise.

## Reliability & Failure Handling

- **Auditor failures** — no usable `response.md` → write `error.json` to the run dir, skip grading; validate_runs flags it for re-run.
- **Grader JSON** — graders write the file themselves; validate_runs catches malformed/incomplete output. One re-prompt, then `grading_error.txt` + ungraded.
- **Never write malformed grading.json** — an ungraded cell is recoverable, a corrupt one silently poisons aggregation.

## Skill Comparability (read before interpreting the leaderboard)

Only **full-audit skills** (complete vulnerability list) are comparable on recall/F1:

- **Full auditors** — `scv-scan`, `ethskills/audit`, `ethskills/security`, `pashov-skills/solidity-auditor`, `sc-auditor/security-auditor`, `qs_skills/behavioral-state-analysis`. Compare head-to-head.
- **Narrow single-category analyzers** — most `qs_skills` (reentrancy, dos-griefing, oracle-flashloan, ...). Recall structurally capped; don't rank vs full auditors.
- **Non-enumeration skills** — `pashov-skills/x-ray`, `qs_skills/defender`, `trailofbits/{audit-context-building,code-maturity-assessor,token-integration-analyzer}`. Score ≈0 recall by design.

## Naming Convention

- Skill names use `/` (e.g. `pashov-skills/solidity-auditor`); filesystem dirs use `__`.
- Run dirs: `results/runs/<skill_dir>/<eval_id>/<ts>r<rep>/` (legacy suffixes: `D`/`E` tooling A/B, `P2` pass-2, `B*` baseline).

## Results Format

### run_metadata.json (written by prepare_run.py; agent appends duration/tokens)
```json
{
  "skill": "scv-scan", "skill_path": "skills/scv-scan/SKILL.md",
  "eval_id": "vfp_00001", "timestamp": "20260705T101500r1",
  "is_baseline": false, "model": "claude-sonnet-4-6",
  "tooling": "disabled", "rep": 1, "experiment": "sonnet-rep3",
  "prompt_version": "auditor_source.md@2dff46521684",
  "grader_prompt_version": "grader.md@c0594ed83585",
  "skill_sha": "ae93d2ae98b99c99", "contracts_sha": "f1a3e810aab07f67",
  "duration_seconds": 312, "tokens": {"total": 451234}
}
```

### grading.json (grader-written; orchestrator merges run_metadata + grading_meta)
```json
{
  "findings": [{"id": 0, "title": "...", "severity": "High", "found": true, "evidence": "..."}],
  "false_positive_details": [{"title": "...", "claimed_severity": "High", "quote": "...", "why_unmatched": "..."}],
  "false_positives": 2,
  "summary": {"total": 8, "found": 5, "missed": 3, "recall": 0.625, "false_positives": 2, "precision": 0.714},
  "run_metadata": {"...": "copied from run_metadata.json"},
  "grading_meta": {"model": "claude-opus-4-8", "tokens": {"total": 98765}}
}
```

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/prepare_run.py` | Deterministic experiment prep: workspaces, prompts, manifests, cells |
| `scripts/render_prompt.py` | Strict template renderer + version hashes (used by prepare_run) |
| `scripts/validate_runs.py` | Post-run integrity checks; lists cells to re-run |
| `scripts/aggregate.py` | Leaderboard; `--experiment` = manifest-selected, rep-averaged, bootstrap CIs |
| `scripts/rank_analysis.py` | Per-model CIs + Holm-corrected paired tests (macro t + per-finding McNemar) |
| `scripts/check_tooling.py` | Verify + version-stamp the security toolchain |
| `scripts/make_canary.py` | Build contamination-canary eval variants |
| `scripts/import_recent_audit.py` | Import post-cutoff audits as fresh compilable evals |
| `scripts/grader_reliability.py` | Repeat-grading agreement (kappa) |
| `scripts/grader_calibration.py` | Grader accuracy vs human labels |
| `scripts/baseline_compare.py` / `model_compare.py` / `multipass_analysis.py` / `tooling_compare.py` | Focused paired analyses (see FINDINGS.md §10) |
| `scripts/compile_eval.py` / `discover_compilable.py` | Scaffold harness for legacy evals |
| `scripts/discover_skills.py` | Scan skills/ for SKILL.md, update skills.json |
| `scripts/token_usage.py` / `persist_token_usage.py` | Token reconstruction from transcripts |
| legacy: `run_eval.py`, `grade.py`, `run_benchmark.sh`, `setup_*.py` | Superseded by prepare_run.py; kept for provenance |

## Key Design Principles

1. **Real workspace** — each auditor gets a real filesystem: full skill tree + contracts (or a compiling project). Any tool, any script.
2. **Full tool access** — subagents are general-purpose; tooling runs additionally get the whole security toolchain on PATH.
3. **Isolation** — workspace contains ONLY skill + code. prepare_run.py asserts ground truth is absent.
4. **Determinism everywhere but the model** — prompts, workspaces, selection, aggregation are all scripted and hashed; the only nondeterminism left is the model itself, which is what repetitions + CIs measure.
5. **Parallelism** — auditors/graders run concurrently (background Agents or Workflow).
6. **Compatibility** — legacy result formats still aggregate; new fields are additive.
