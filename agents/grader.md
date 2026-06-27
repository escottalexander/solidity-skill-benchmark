# Grader Subagent

This file is a reference for the orchestrating agent. It describes how to construct the prompt for a grader subagent.

## When to spawn

Spawn one grader subagent per completed audit run. Multiple graders can run in parallel.

## How to build the prompt

**Preferred (file-based, scales cleanly):** Give the grader the absolute paths to the ground-truth `findings.json` and the saved `response.md`, and have it read both with its own tools and write `grading.json` directly to the run directory. This avoids the orchestrator reading large audit responses into its own context just to paste them into the prompt. Use the file-based template below. The grader is allowed to read `findings.json` — it is the grader, not the auditor.

**Fallback (inline):** If you must, read `findings.json` and `response.md` yourself and inject them into the prompt as literal text (older template, still valid).

When matching, treat skill-specific "Leads"/"unverified"/"possible" sections strictly: only credit such an entry as "found" if it specifically identifies the ground-truth finding's root cause, not if it merely raises the area as an open question.

## File-based prompt template (preferred)

```
You are grading a security audit response against a set of known vulnerabilities.

Read these two files with your tools:
- Ground truth findings: {FINDINGS_JSON_PATH}
- Audit response to grade: {RESPONSE_MD_PATH}

For EACH finding in the ground-truth file, determine whether the audit response identified it.

A finding counts as "found" if the response describes the same vulnerability — same root cause and affected code — even with different wording. Be generous on wording, strict on substance: a vague category mention ("watch out for reentrancy") does not count. Treat any "Leads"/"unverified"/"possible" section in the response strictly — only credit it if it specifically identifies the finding's root cause, not if it merely raises the area as an open question.

Also count substantive findings in the response (High/Medium/Critical) that do NOT match any known vulnerability (false positives). Ignore informational notes and gas optimizations.

Then WRITE your grading as JSON to this exact path: {GRADING_JSON_PATH}
The JSON must have this exact shape:
{
    "findings": [
        {"id": <int>, "title": "<str>", "severity": "<str>", "found": <bool>, "evidence": "<brief quote or 'Not found'>"}
    ],
    "false_positives": <int>,
    "summary": {
        "total": <int>, "found": <int>, "missed": <int>,
        "recall": <found/total>, "false_positives": <int>,
        "precision": <found/(found+false_positives), or 1.0 if none reported>
    }
}

After writing the file, reply with a single line: the recall and precision. Do not paste the full JSON back.
```

The orchestrator then reads `{GRADING_JSON_PATH}`, merges in `run_metadata` (copied from `run_metadata.json`) and `grading_meta` (`{"model": ..., "tokens": {"total": <grader subagent_tokens>}}`), and writes the final `grading.json`. If the grader's file is missing or doesn't parse, re-prompt once; if it still fails, leave the cell ungraded (don't write malformed JSON).

## Prompt template (inline fallback)

```
You are grading a security audit response. You must determine which known vulnerabilities were found.

## Known Vulnerabilities (Ground Truth)

{FOR_EACH_FINDING}
--- Finding {ID} ---
Title: {TITLE}
Severity: {SEVERITY}
Description: {DESCRIPTION}
Location: {LOCATION}
Files: {FILES}

{END_FOR}

## Audit Response to Grade

{RESPONSE_TEXT}

## Instructions

For EACH known vulnerability above, determine if the audit response identified it.

A finding counts as "found" if the response describes the same vulnerability — it does NOT need to use the exact same title or wording. What matters is whether the core vulnerability (the root cause and affected code) was identified.

Be generous in matching: if the response describes the same bug with different words, it counts.
Be strict on substance: a vague mention of a category (e.g. "watch out for reentrancy") without identifying the specific instance does NOT count.

Also count how many distinct findings in the audit response do NOT match any known vulnerability (false positives). Only count substantive findings (High/Medium/Critical), not informational notes or gas optimizations.

Respond with ONLY valid JSON in this exact format:
{
    "findings": [
        {
            "id": <finding number>,
            "title": "<finding title>",
            "severity": "<severity>",
            "found": true or false,
            "evidence": "<brief quote or description from the response, or 'Not found'>"
        }
    ],
    "false_positives": <number of substantive findings not in ground truth>,
    "summary": {
        "total": <total known findings>,
        "found": <number found>,
        "missed": <number missed>,
        "recall": <found/total as decimal>,
        "false_positives": <count>,
        "precision": <found/(found+false_positives) as decimal, or 1.0 if none reported>
    }
}
```

## Subagent configuration

- **subagent_type**: omit (use default general-purpose)
- **model**: use `sonnet` for cost-efficient grading
- **description**: `"Grade {eval_id} for {skill_name}"`
- **prompt**: The filled-in template above

## What to do with the result

The subagent returns JSON text. Parse it and save to:
```
results/runs/{skill_dir_name}/{eval_id}/{timestamp}/grading.json
```

The grading JSON should also include:
- `run_metadata` — copied from the run's `run_metadata.json`
- `grading_meta` — `{"model": "<grader model>"}`

## Grading metrics

- **Recall** = found / total (what fraction of real vulns were caught)
- **Precision** = found / (found + false_positives) (how many reported vulns are real)
- **F1** = 2 * (precision * recall) / (precision + recall)
