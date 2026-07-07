# Auditor Subagent

Reference for the orchestrating agent: how auditor subagents are prepared and spawned.

## The frozen-prompt rule

**Never hand-write or paraphrase an auditor prompt.** The exact prompts are
frozen templates in `agents/prompts/`:

| Template | Used for |
|---|---|
| `auditor_source.md` | skill run, source-only (contracts don't compile) |
| `auditor_source_baseline.md` | no-skill baseline, source-only |
| `auditor_tooling.md` | skill run, compiling project + security tools |
| `auditor_tooling_baseline.md` | no-skill baseline, compiling project + tools |

`scripts/prepare_run.py` renders them deterministically (via
`scripts/render_prompt.py`), saves the rendered prompt as `prompt.md` in each
run directory, and records the template version
(`<file>@<sha256[:12]>`) in `run_metadata.json`. Any two runs can therefore be
proven prompt-identical. Editing a template changes its version string — old
runs stay attributable to the exact prompt they used.

## Workspace setup

`prepare_run.py` owns this — do not build workspaces by hand. Per cell it:

1. creates a temp workspace with `skill/` (full skill directory; omitted for
   baseline) and either `contracts/` (source-only) or `project/` (a compiling
   Foundry project with `lib/` symlinked per cell so concurrent tool runs don't
   clash)
2. **asserts `findings.json` / `metadata.json` are absent** from the workspace
3. creates the run dir with `run_metadata.json` (model, rep, experiment,
   prompt versions, skill + contracts content hashes, tool versions for the
   tooling arm), `prompt.md`, and `grader_prompt.md`
4. writes one `cell_<i>.json` per cell (one-cell-per-file — see CLAUDE.md)

## Spawning

Spawn one auditor per cell, passing the cell's `auditorBootstrap` string as the
subagent prompt VERBATIM:

```
Agent({
  description: "Audit {eval_id} ({experiment})",
  model: <the model recorded in run_metadata.json>,
  prompt: cell.auditorBootstrap   // "Read the file .../prompt.md ... follow exactly"
})
```

- **subagent_type**: omit (general-purpose, full tool access)
- The auditor writes its report directly to the run dir's `response.md`
  (the path is baked into the rendered prompt), so the orchestrator never
  re-transcribes reports.

## Failure handling

If a subagent errors or produces no usable `response.md`, write `error.json`
to the run dir and skip grading for that cell. Then find and re-run holes with:

```bash
python3 scripts/validate_runs.py --experiment <name>
```

## Result capture

The Agent tool result ends with a `<usage>` block. Append to the cell's
`run_metadata.json`: `duration_seconds` (from `duration_ms`) and
`tokens: {"total": <subagent_tokens>}`.
