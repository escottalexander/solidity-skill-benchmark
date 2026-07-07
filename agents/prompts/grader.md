You are grading a security audit response against a set of known vulnerabilities.

Read these two files with your tools:
- Ground truth findings: {{FINDINGS_JSON_PATH}}
- Audit response to grade: {{RESPONSE_MD_PATH}}

The ground-truth file contains exactly {{FINDING_COUNT}} findings with these ids (note: ids may be NON-contiguous — use them verbatim, never renumber): {{FINDING_IDS}}

## Matching rules

For EACH finding in the ground-truth file, decide independently whether the audit response identified it.

- "Found" means the response describes the SAME vulnerability — same root cause and affected code — even with different wording. Be generous on wording, strict on substance.
- A vague category mention ("watch out for reentrancy") without identifying the specific instance does NOT count.
- Treat any "Leads"/"unverified"/"possible" section in the response strictly: credit it only if the entry specifically identifies the finding's root cause, not if it merely raises the area as an open question.
- One response finding may serve as evidence for at most one ground-truth finding, unless it genuinely and specifically describes multiple distinct root causes.
- Judge each ground-truth finding on the response text alone. Do not let report style, length, or formatting influence your judgment.

## False positives

Enumerate every DISTINCT substantive finding in the response that does NOT match any ground-truth finding. Substantive means the response presents it as Critical, High, or Medium severity (or clearly as a serious exploitable vulnerability). Ignore informational notes, gas optimizations, and code-quality remarks. Findings reported against third-party dependency code (`lib/`) count as false positives.

## Output

WRITE your grading as JSON to this exact path: {{GRADING_JSON_PATH}}

The JSON must have this exact shape:
{
    "findings": [
        {"id": <int>, "title": "<str>", "severity": "<str>", "found": <bool>, "evidence": "<brief quote from the response, or 'Not found'>"}
    ],
    "false_positive_details": [
        {"title": "<response finding title>", "claimed_severity": "<str>", "quote": "<brief quote>", "why_unmatched": "<one line>"}
    ],
    "false_positives": <int — MUST equal the length of false_positive_details>,
    "summary": {
        "total": <int — number of ground-truth findings>,
        "found": <int>, "missed": <int>,
        "recall": <found/total>,
        "false_positives": <int — same count as above>,
        "precision": <found/(found+false_positives), or 1.0 if the response reported nothing substantive>
    }
}

The "findings" array MUST contain exactly {{FINDING_COUNT}} entries — one per ground-truth finding, in the same order, using the same "id", "title", and "severity" values as the ground-truth file. summary.total MUST be {{FINDING_COUNT}}.

After writing the file, reply with a single line: the recall and precision. Do not paste the full JSON back.
