# Solidity Skill Benchmark

Benchmarks Claude Code skills for Solidity smart contract security auditing. This agent orchestrates the entire pipeline — preparing workspaces, spawning subagents for auditing and grading, saving results, and aggregating leaderboards.

## Repository Structure

- `evals/` — 300 eval cases (`vfp_00001` .. `vfp_00300`), each containing:
  - `contracts/` — Solidity source files to audit
  - `findings.json` — ground truth vulnerabilities (never shown to auditor)
  - `metadata.json` — project info, CWE tags, severity counts
- `evals/evals.json` — registry of all 300 evals
- `evals/core_subset.json` — curated subset of ~27 diverse evals (default for benchmarks)
- `skills/` — Claude Code skills to benchmark
- `skills.json` — manifest mapping skill names to SKILL.md paths; `enabled: true` for active skills
- `agents/` — subagent prompt templates (auditor.md, grader.md)
- `scripts/` — utility scripts (aggregate.py, discover_skills.py)
- `results/` — output: `runs/`, `history/`, `benchmark.json`
- `site/` — leaderboard HTML (reads `site/data.json`)

## How It Works (Agent-Led)

This agent is the orchestrator. Instead of shell scripts calling `claude -p`, this agent:

1. **Prepares a workspace** — creates a temp directory with the skill's full directory (SKILL.md + references, scripts, etc.) and the eval's contract files
2. **Spawns an auditor subagent** — points it at the workspace and tells it to follow the skill methodology and audit the contracts using any tools it needs
3. **Saves the audit response** — writes `response.md` and `run_metadata.json`
4. **Spawns a grader subagent** — sends ground truth findings + audit response for evaluation
5. **Saves the grading** — writes `grading.json` with recall/precision/F1
6. **Aggregates** — runs `python3 scripts/aggregate.py` to update the leaderboard

See `agents/auditor.md` and `agents/grader.md` for the subagent prompt templates.

## Running a Single Eval

When the user asks to run a specific eval (e.g., "run scv-scan against vfp_00001"):

### Step 1: Resolve the skill

Read `skills.json` to find the SKILL.md path for the given skill name. The skill directory is the parent of the SKILL.md file (e.g., `skills/scv-scan/` for `skills/scv-scan/SKILL.md`).

### Step 2: Create the workspace

Create an isolated temp directory with the skill's full directory tree and the eval's contracts:

```bash
WORKSPACE=$(mktemp -d /tmp/eval_XXXXXX)
cp -r skills/scv-scan/ $WORKSPACE/skill/        # Full skill dir (SKILL.md + references/, scripts/, etc.)
cp -r evals/vfp_00001/contracts/ $WORKSPACE/contracts/   # Only contracts, never findings.json
```

This gives the subagent a real filesystem to work with — it can read reference files, run scripts, use grep, or anything else the skill methodology requires.

### Step 3: Spawn the auditor subagent

Build the prompt per `agents/auditor.md` and spawn:

```
Agent({
  description: "Audit vfp_00001 with scv-scan",
  model: "sonnet",
  prompt: <constructed prompt pointing at $WORKSPACE>
})
```

The subagent has full tool access (Read, Grep, Glob, Bash, Write, etc.) and works within the workspace directory. It follows the skill instructions and can use any bundled resources.

### Step 4: Save the audit result

Create the run directory and save files:
```
results/runs/<skill_dir>/<eval_id>/<YYYYMMDDTHHMMSS>/
  response.md          — the subagent's audit text
  run_metadata.json    — skill name, eval_id, timestamp, model
```

Skill dir uses `__` for `/` separators (e.g., `pashov-skills__solidity-auditor`).

Then clean up the temp workspace: `rm -rf $WORKSPACE`

### Step 5: Build the grader prompt

1. Read `evals/<eval_id>/findings.json` (ground truth)
2. Read the saved `response.md`
3. Construct the prompt per `agents/grader.md`

### Step 6: Spawn the grader subagent

```
Agent({
  description: "Grade vfp_00001 for scv-scan",
  model: "sonnet",
  prompt: <constructed grading prompt>
})
```

The grader doesn't need a workspace — it receives all data in the prompt.

### Step 7: Save the grading

Parse the grader's JSON response and save to `grading.json` in the run directory. Include the `run_metadata` and `grading_meta` fields for aggregate.py compatibility.

### Step 8: Report results

Print recall, precision, F1, and which findings were found/missed.

## Running a Benchmark

When the user asks to benchmark a skill (e.g., "benchmark scv-scan"):

### Step 1: Select evals

- Default: read `evals/core_subset.json` for the ~27 curated evals
- The user can specify: `--sample N` (random subset), specific eval IDs, or `--all`

### Step 2: Spawn auditor subagents in parallel

For each eval:
1. Create its workspace (via Bash, can do multiple in one command)
2. Spawn an auditor subagent with `run_in_background: true`

Spawn all in the same turn for maximum parallelism.

### Step 3: Save results and spawn graders

As each auditor completes, save its response, clean up the workspace, and spawn a grader subagent (also in background where possible).

### Scaled runs via the Workflow tool

For large matrices (many skills × evals), a deterministic `Workflow` that pipelines audit→grade per cell is far more efficient than hand-managing dozens of background `Agent` calls. Hard-won rules (a pilot run lost 7/29 cells to violating the first one):

- **One cell per file — never "read a shared manifest and take index N".** Workflow scripts have no filesystem access, so subagents must read their inputs from disk. If you point every subagent at the *same* manifest array and tell it "use element N", subagents reliably grab the **wrong index** — some cells get written 2–3× and others get zero. Instead, the Bash pre-step writes one `cell_<i>.json` (a single object, not an array) per cell, and each subagent reads only its own file. (Written files stay internally consistent even under the bug — each reads workspace[j] and writes response[j] — so the failure shows up as *coverage holes*, not corruption.)
- **Pre-step owns isolation + setup.** A Bash/Python pre-step creates each isolated workspace (skill dir + contracts, **never** `findings.json` — assert it's absent), the run dir + `run_metadata.json`, and the per-cell files. Pass only tiny data to the workflow as `args` (counts, modes, labels) — and note `args` arrives as a JSON **string**, so `JSON.parse` it in the script (`typeof args === 'string' ? JSON.parse(args) : args`).
- **Subagents write their own outputs** (`response.md`, `grading.json`) to absolute paths from their cell file — the orchestrator never re-transcribes large reports.
- **Always validate coverage afterward and re-run holes.** Check every cell has a non-empty `response.md` and a parseable `grading.json` (right `summary` keys). Re-run only the missing/failed cells via a small recovery workflow (same one-cell-per-file pattern). A contamination check is cheap insurance: confirm each `response.md` mentions its own eval's contract names.

### Step 4: Aggregate

After all grading is complete:
```bash
python3 scripts/aggregate.py
```

This produces:
- `results/benchmark.json` — full leaderboard
- `results/history/benchmark_<ts>.json` — historical snapshot
- `site/data.json` — data for the web UI

### Step 5: Report the leaderboard

Print the summary table with rank, skill, F1, recall, precision, and eval count.

## Reliability & Failure Handling

A full benchmark spawns hundreds of auditor + grader subagents; some will fail (timeouts, crashes, malformed output). Handle this explicitly:

- **Auditor failures** — if a subagent errors or returns no usable audit text, write `error.json` to the run dir (instead of `response.md`) and skip grading for that cell. `aggregate.py` already falls back to the most recent run that has a `grading.json`, so a failed re-run won't shadow an earlier success.
- **Grader JSON extraction** — graders are told to return *only* JSON, but models often wrap it in prose or ```` ```json ```` fences. Before saving `grading.json`, extract the JSON (strip fences, take the outermost `{...}`) and validate it parses with the expected `findings`/`summary` keys. If it doesn't parse after one re-prompt, save the raw text to `grading_error.txt` and leave the cell ungraded rather than writing malformed JSON.
- **Re-running missing cells** — after a run, diff the (skill × eval) matrix against `results/runs/` to find cells with no valid `grading.json`, and re-run only those. Don't re-run completed cells.
- **Duration & tokens** — the Agent tool result ends with a `<usage>` block containing `subagent_tokens` and `duration_ms`. Capture both: record `duration_seconds` (from `duration_ms`) and `tokens: {"total": <subagent_tokens>}` in `run_metadata.json`. `aggregate.py` reads `tokens.total`. **Cost is NOT surfaced** (no per-token price split), so `total_cost_usd` stays `0` and the leaderboard's Cost column stays empty — that part is expected. Token count and duration *do* populate.

## Skill Comparability (read before interpreting the leaderboard)

The grader scores recall/precision against an enumerated findings list, so only **full-audit skills** (those that produce a complete vulnerability list) are directly comparable on F1. Three kinds of enabled skills are *not* apples-to-apples:

- **Full auditors** — e.g. `scv-scan`, `ethskills/audit`, `ethskills/security`, `pashov-skills/solidity-auditor`, `sc-auditor/security-auditor`, `qs_skills/behavioral-state-analysis`. Compare these head-to-head.
- **Narrow single-category analyzers** — e.g. most `qs_skills` (reentrancy, dos-griefing, oracle-flashloan, etc.). They target one vuln class, so recall is structurally capped on mixed-finding evals. Don't rank them against full auditors.
- **Non-enumeration skills** — e.g. `pashov-skills/x-ray` (pre-audit threat model), `qs_skills/defender` (deploy-readiness), `trailofbits/{audit-context-building,code-maturity-assessor,token-integration-analyzer}`. These don't output a vuln list and will score ≈0 recall by design.

When benchmarking a mixed set, tier the leaderboard by skill type or restrict the headline board to full auditors.

## Baseline Runs

For baseline comparisons (no skill), create the workspace with only contracts (no `skill/` directory). Omit the skill methodology section from the auditor prompt. Use `"baseline"` as the skill name and `is_baseline: true` in metadata.

## Skill Manifest (`skills.json`)

Maps human-readable skill names to SKILL.md paths:

```json
{
  "skills": {
    "scv-scan": { "path": "skills/scv-scan/SKILL.md", "enabled": true },
    "pashov-skills/solidity-auditor": { "path": "skills/pashov-skills/solidity-auditor/SKILL.md", "enabled": true }
  }
}
```

### Discover and update the manifest

```bash
python3 scripts/discover_skills.py            # list all SKILL.md files found
python3 scripts/discover_skills.py --update   # add new discoveries to skills.json
```

Then edit `skills.json` to set `enabled: true` for skills to include.

## Naming Convention

- Skill names use `/` as separator (e.g. `pashov-skills/solidity-auditor`)
- Filesystem directories use `__` instead (e.g. `results/runs/pashov-skills__solidity-auditor/`)
- The human-readable name and original SKILL.md path are recorded in `run_metadata.json`

## Results Format

### run_metadata.json
```json
{
  "skill": "scv-scan",
  "skill_path": "skills/scv-scan/SKILL.md",
  "eval_id": "vfp_00001",
  "timestamp": "20260408T120000",
  "is_baseline": false,
  "model": "sonnet"
}
```

### grading.json
```json
{
  "findings": [
    {"id": 1, "title": "...", "severity": "High", "found": true, "evidence": "..."}
  ],
  "false_positives": 2,
  "summary": {
    "total": 8, "found": 5, "missed": 3,
    "recall": 0.625, "false_positives": 2, "precision": 0.714
  },
  "run_metadata": { "...same as run_metadata.json..." },
  "grading_meta": { "model": "sonnet" }
}
```

## Utility Scripts

These scripts remain useful as helpers:

| Script | Purpose |
|--------|---------|
| `scripts/aggregate.py` | Collect all grading.json files, compute stats, produce leaderboard |
| `scripts/discover_skills.py` | Scan skills/ for SKILL.md files, update skills.json |
| `scripts/select_core_subset.py` | Select diverse eval subset (already run) |
| `scripts/import_forge_curated.py` | Import FORGE-Curated data into evals/ (already run) |
| `scripts/grade.py` | Standalone grading via `claude -p` (legacy fallback) |
| `scripts/run_eval.py` | Standalone eval via `claude -p` (legacy fallback) |
| `scripts/run_benchmark.sh` | Shell-based benchmark orchestration (legacy fallback) |

## Key Design Principles

1. **Real workspace** — Each auditor subagent gets a temp directory with the full skill tree (SKILL.md + references, scripts, etc.) and the contracts. It can use any tool — read files, run scripts, grep, bash — just like a real user would.
2. **Full tool access** — Subagents are general-purpose (not restricted to Read/Glob/Grep). If a skill says "run this script" or "use this tool", the subagent can do it.
3. **Isolation** — The workspace contains only the skill and contracts. Findings are never copied in. The subagent is instructed to work only within the workspace.
4. **Parallelism** — Multiple auditor/grader subagents can run concurrently using `run_in_background`.
5. **Compatibility** — Results use the same directory structure and JSON formats as the legacy scripts, so aggregate.py works unchanged.
6. **Skill injection via workspace** — The skill's full directory is copied into the workspace, so all bundled resources (reference docs, scripts, assets) are available — not just the SKILL.md file.
