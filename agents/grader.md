# Grader Subagent

Reference for the orchestrating agent: how grader subagents are spawned.

## The frozen-prompt rule

The grader prompt is the frozen template `agents/prompts/grader.md`, rendered
per cell by `scripts/prepare_run.py` and saved as `grader_prompt.md` in the run
directory (version recorded in `run_metadata.json` as
`grader_prompt_version`). **Never hand-write a grader prompt.**

The template is file-based: the grader reads the ground-truth `findings.json`
and the run's `response.md` itself, and writes `grading.json` directly to the
run dir. The grader is allowed to read `findings.json` — it is the grader, not
the auditor.

## Spawning

One grader per completed audit, passing the cell's `graderBootstrap` string
verbatim:

```
Agent({
  description: "Grade {eval_id} ({experiment})",
  model: <grader model — use the STRONGEST available; grading quality gates everything>,
  prompt: cell.graderBootstrap
})
```

Keep the description neutral (don't leak the skill name into anything the
grader sees; the prompt file already contains only paths).

## Output contract (enforced by validate_runs.py)

`grading.json` must contain:
- `findings[]` — exactly one entry per ground-truth finding, same ids/order
- `false_positive_details[]` — every unmatched substantive response finding,
  itemized with a quote (this makes FP counts auditable)
- `false_positives` — must equal `len(false_positive_details)`
- `summary{total, found, missed, recall, false_positives, precision}`

After grading completes, the orchestrator merges `run_metadata` (copied from
`run_metadata.json` — never trust a grader-written copy) and `grading_meta`
(`{"model": ..., "tokens": {"total": <grader subagent_tokens>}}`) into
`grading.json`. If the file is missing or unparseable, re-prompt once; if it
still fails, save the raw reply to `grading_error.txt` and leave the cell
ungraded rather than writing malformed JSON.

## Grader quality assurance

The grader is the benchmark's measurement instrument. Two harnesses keep it
honest:

- `scripts/grader_reliability.py` — re-grades a deterministic sample of
  responses k times with the SAME frozen prompt and reports percent agreement,
  pooled Cohen's kappa, and FP-count spread. Run after any grader/template/model
  change.
- `scripts/grader_calibration.py` — emits a stratified sample of
  (response, ground-truth finding) pairs for HUMAN labeling
  (`results/calibration/labels_todo.json`), then scores the grader against the
  human labels. Leaderboard gaps smaller than the grader's measured error rate
  are noise.

## Grading metrics

- **Recall** = found / total (what fraction of real vulns were caught)
- **Precision** = found / (found + false_positives)
- **F1** = 2PR/(P+R)
- Note: precision penalizes real-but-unlisted findings (some "false positives"
  are genuine bugs the original audit missed). Applied equally to all skills,
  so relative ranking holds, but absolute precision reads low.
