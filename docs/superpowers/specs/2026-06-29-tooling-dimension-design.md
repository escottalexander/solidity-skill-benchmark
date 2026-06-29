# Tooling Dimension — Design

Date: 2026-06-29
Status: Approved, implementing

## Goal

Add a new benchmark dimension — **tooling enabled vs disabled** — to measure how
much giving the audit skills real static-analysis/fuzzing tools changes accuracy
(recall/precision) versus the existing source-only runs. The A/B comparison is
the product.

## Key constraint discovered during design

The existing eval contracts are **partial audit snapshots** with unresolved
imports. Of the 27 `core_subset` evals, only ~2-3 can be compiled; compile-needing
tools (Slither, Aderyn, Mythril, Echidna, Halmos) cannot run on the rest. A probe
across all 300 evals found **26 compile-candidates** (no missing local files +
only installable deps). One candidate (`vfp_00078`) was verified to build cleanly
with OZ v5 + remappings, confirming the harness approach.

Therefore the A/B runs on a **new compilable set drawn from the 300**, not on
core_subset. Both arms (tools off + tools on) run on this identical set so the
comparison is perfectly paired.

## Decisions

- **Eval set:** assemble a compilable set (~15-22 evals) from the 26 candidates.
- **Model:** Sonnet only, first pass (isolate the tooling variable, lowest cost).
- **Skills:** the same 6 full-auditor skills used elsewhere.
- **Tools:** full suite installed (Slither, Aderyn, Mythril, Echidna, Halmos +
  solc/forge). Agents run whatever their methodology calls for, including writing
  their own Echidna/Halmos harness. We do NOT pre-write harnesses. Honest caveat:
  fuzzers only contribute if an agent writes a harness, so their measured lift may
  be small — that is a finding, not a setup failure.
- **Who compiles:** a deterministic pre-step owns compilation + tool install; the
  agent consumes a pre-built, compiling project and runs tools itself.

## Data model

`run_metadata.json` gains a `tooling` axis:

```json
{ "skill": "...", "eval_id": "...", "model": "...",
  "tooling": "disabled" | "enabled",
  "tools_available": ["slither","aderyn","mythril","echidna","halmos"],
  "tools_invoked": ["slither"]   // backfilled from transcript scan
}
```

All 162 existing runs are backfilled `"tooling": "disabled"`. `aggregate.py`'s
grouping key becomes **(skill, model, tooling)** — enabled and disabled rows
coexist exactly like sonnet/opus do today.

## Components

1. `scripts/compile_eval.py` — build harness. Per eval: scaffold a Foundry
   project, detect OZ major version from import paths (v4 markers like
   `/security/`, v5 markers like `utils/Panic.sol`; try v5 then v4 on failure),
   install installable deps (OZ +/- upgradeable, solady, solmate, uniswap-v3-core,
   forge-std), write `remappings.txt`, let Foundry pick solc from the pragma, run
   `forge build`. Emit `evals/<id>/build_status.json`.
2. `scripts/discover_compilable.py` — run the harness over the 26 candidates,
   write `evals/tooling_set.json` with the evals that built. **Gate: if < ~12
   compile, pause and reconsider.**
3. `scripts/setup_tooling.sh` — reproducible install of the suite: a `.venv-tools`
   venv for slither/mythril/halmos, `cargo install` aderyn, Foundry already
   present, solc via the venv. Docker `eth-security-toolbox` documented as a
   fallback. Verifies each tool with `--version`.
4. `scripts/backfill_tooling.py` — stamp `"tooling":"disabled"` onto all existing
   run_metadata.json and embedded grading run_metadata.
5. `aggregate.py` — add `tooling` to the grouping key + a Tooling column.
6. `scripts/tooling_compare.py` — mirror of `model_compare.py`: per skill,
   tools-on vs tools-off on the same evals, micro-recall + paired McNemar =
   tooling lift. Also reports, per enabled run, which tools the agent actually
   invoked (transcript scan), to distinguish real tool use from "ignored them."
7. `rank_analysis.py` — add a `TOOLING` env filter alongside `RANK_MODEL`.

## Run methodology

- **Tools-off arm (re-baseline):** existing source-only workspace (skill +
  contracts, no deps, no tools) and prompt, on the compilable set.
- **Tools-on arm:** workspace contains skill + the pre-built compiling Foundry
  project (deps + remappings + artifacts); tools on PATH. Prompt drops the "no
  tools" constraint and states the project builds and which tools are installed,
  to be used per the skill's methodology.
- Orchestration uses the established one-cell-per-file pattern; idempotent
  auditor/grader so session-limit interruptions resume cleanly.

## Build order

1. Build harness + discover compilable set (the gate).
2. Tool install + backfill + schema/aggregate changes.
3. Run both arms (Sonnet × 6 skills × compilable set), validate coverage.
4. Reporting (`tooling_compare.py`) + interpretation.

## Honesty / instrumentation

- All tooling comparisons scoped to the compilable set; report compile rate.
- Per enabled run, record and report which tools were actually invoked.
- A skill that ignores the tools and reads source anyway is a valid (and
  interesting) outcome, not a bug.
