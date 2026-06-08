# Grader Subagent

This file is a reference for the orchestrating agent. It describes how to construct the prompt for a grader subagent.

## When to spawn

Spawn one grader subagent per completed audit run. Multiple graders can run in parallel.

## How to build the prompt

Read these inputs and inject them into the prompt template below:

1. **Ground truth findings** — Read `evals/<eval_id>/findings.json`. Format each finding with its id, title, severity, description, location, and files.
2. **Audit response** — Read the `response.md` from the completed audit run.

## Prompt template

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
