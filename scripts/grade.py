#!/usr/bin/env python3
"""
Grade a skill's response against ground truth findings.

Uses LLM-as-judge: for each known finding, determines whether the skill's
response identified it (even if worded differently).

Usage: python3 scripts/grade.py <run_dir> <eval_id>
"""

import json
import subprocess
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent


def grade_run(run_dir: Path, eval_id: str) -> dict:
    """Grade a single run against ground truth."""
    eval_dir = PROJ_ROOT / "evals" / eval_id
    findings_path = eval_dir / "findings.json"
    response_path = run_dir / "response.md"

    if not findings_path.exists():
        print(f"Error: No findings at {findings_path}")
        sys.exit(1)
    if not response_path.exists():
        print(f"Error: No response at {response_path}")
        sys.exit(1)

    with open(findings_path) as f:
        findings = json.load(f)
    with open(response_path) as f:
        response = f.read()

    # Build grading prompt
    findings_text = ""
    for i, finding in enumerate(findings):
        findings_text += f"""
--- Finding {i+1} ---
Title: {finding['title']}
Severity: {finding['severity']}
Description: {finding['description']}
Location: {', '.join(finding.get('location', []))}
Files: {', '.join(finding.get('files', []))}
"""

    grading_prompt = f"""You are grading a security audit response. You must determine which known vulnerabilities were found.

KNOWN VULNERABILITIES (ground truth):
{findings_text}

AUDIT RESPONSE TO GRADE:
{response}

For EACH known vulnerability above, determine if the audit response identified it.
A finding counts as "found" if the response describes the same vulnerability — it does NOT need to use the exact same title or wording. What matters is whether the core vulnerability (the root cause and affected code) was identified.

Be generous in matching: if the response describes the same bug with different words, it counts.
Be strict on substance: a vague mention of a category (e.g. "watch out for reentrancy") without identifying the specific instance does NOT count.

Also count how many distinct findings in the audit response do NOT match any known vulnerability (false positives). Only count substantive findings (High/Medium/Critical), not informational notes or gas optimizations.

Respond with ONLY valid JSON in this exact format:
{{
    "findings": [
        {{
            "id": <finding id>,
            "title": "<finding title>",
            "severity": "<severity>",
            "found": true/false,
            "evidence": "<brief quote or description of where in the response this was found, or 'Not found' if missed>"
        }}
    ],
    "false_positives": <number of substantive findings not matching any known vulnerability>,
    "summary": {{
        "total": <total known findings>,
        "found": <number found>,
        "missed": <number missed>,
        "recall": <found/total as float>,
        "false_positives": <count>,
        "precision": <found/(found+false_positives) as float, or 1.0 if no findings reported>
    }}
}}"""

    # Call claude -p to grade
    result = subprocess.run(
        ["claude", "-p", grading_prompt, "--output-format", "json", "--max-turns", "1"],
        capture_output=True, text=True, timeout=120
    )

    # Parse grading response
    grading_data = None
    try:
        raw = result.stdout.strip()
        grading_data = json.loads(raw)
        if isinstance(grading_data, list):
            text_parts = [b.get("text", "") for b in grading_data if b.get("type") == "text"]
            raw_text = "\n".join(text_parts)
        elif isinstance(grading_data, dict) and "result" in grading_data:
            raw_text = grading_data["result"]
        else:
            raw_text = raw

        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            grading = json.loads(raw_text[start:end])
        else:
            raise ValueError("No JSON found in grading response")

    except (json.JSONDecodeError, ValueError) as e:
        print(f"Warning: Could not parse grading response: {e}")
        print(f"Raw output: {result.stdout[:500]}")
        grading = {
            "findings": [
                {"id": f["id"], "title": f["title"], "severity": f["severity"],
                 "found": False, "evidence": "Grading parse error"}
                for f in findings
            ],
            "false_positives": 0,
            "summary": {
                "total": len(findings),
                "found": 0,
                "missed": len(findings),
                "recall": 0.0,
                "false_positives": 0,
                "precision": 0.0,
            },
            "grading_error": str(e),
        }

    # Extract grading cost/token metadata from the claude response
    grading_meta = {}
    if isinstance(grading_data, dict):
        model_usage = grading_data.get("modelUsage", {})
        model_name = next(iter(model_usage), "") if model_usage else ""
        model_info = model_usage.get(model_name, {}) if model_name else {}
        usage = grading_data.get("usage", {})
        grading_meta = {
            "model": model_name,
            "total_cost_usd": grading_data.get("total_cost_usd", 0),
            "duration_ms": grading_data.get("duration_ms", 0),
            "tokens": {
                "input": model_info.get("inputTokens", usage.get("input_tokens", 0)),
                "output": model_info.get("outputTokens", usage.get("output_tokens", 0)),
                "cache_read": model_info.get("cacheReadInputTokens",
                                usage.get("cache_read_input_tokens", 0)),
                "cache_creation": model_info.get("cacheCreationInputTokens",
                                    usage.get("cache_creation_input_tokens", 0)),
            },
        }
    grading["grading_meta"] = grading_meta

    # Load run metadata if available
    meta_path = run_dir / "run_metadata.json"
    timing_path = run_dir / "timing.json"
    if meta_path.exists():
        with open(meta_path) as f:
            grading["run_metadata"] = json.load(f)
    elif timing_path.exists():
        with open(timing_path) as f:
            grading["timing"] = json.load(f)

    # Save grading
    with open(run_dir / "grading.json", "w") as f:
        json.dump(grading, f, indent=2)

    return grading


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/grade.py <run_dir> <eval_id>")
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    eval_id = sys.argv[2]

    grading = grade_run(run_dir, eval_id)

    summary = grading.get("summary", {})
    print(f"Results for {eval_id}:")
    print(f"  Found: {summary.get('found', 0)}/{summary.get('total', 0)}")
    print(f"  Recall: {summary.get('recall', 0):.1%}")
    print(f"  False positives: {summary.get('false_positives', 0)}")
    print(f"  Precision: {summary.get('precision', 0):.1%}")


if __name__ == "__main__":
    main()
