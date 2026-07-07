You are performing a security audit of Solidity smart contracts.

Your working directory is {{WORKSPACE}}.

## Your Audit Methodology

Read and follow the skill instructions at `skill/SKILL.md`. This defines your audit methodology, including any reference files or scripts you should use. All skill resources (references, scripts, etc.) are in the `skill/` directory.

## Contracts to Audit

The Solidity contracts to audit are in the `contracts/` directory:
{{FILE_LIST}}

## Task

FIRST, verify your inputs exist: list the files in `contracts/`. If the directory is missing, empty, or contains no `.sol` files, do NOT write a report — never reconstruct an audit from the file list in this prompt. Instead write the single line `ERROR: workspace missing input files` to `{{RESPONSE_PATH}}` and stop.

Read and analyze each contract. Identify all security vulnerabilities you can find. For each vulnerability, provide:

1. **Title** — A clear, descriptive name
2. **Severity** — Critical, High, Medium, Low, or Informational
3. **Description** — What the vulnerability is and why it matters
4. **Location** — The affected file(s) and function(s)/line(s)
5. **Recommendation** — How to fix it

Focus on real, exploitable vulnerabilities — not gas optimizations, style issues, or informational notes. Be thorough and systematic.

## Environment Constraints

This is a source-reading audit. The contracts have unresolved imports (OpenZeppelin, etc.), no installed dependencies, and no build setup, so **they will not compile**. Static-analysis tools (Slither, Mythril, Semgrep, solc, Aderyn, Echidna, Halmos) are **not installed**. Do not attempt to install tools, fetch dependencies, or compile — audit by reading the source directly. If the skill methodology calls for a tool you cannot run, apply the equivalent reasoning manually.

## Output

Write your finished audit report to the file `{{RESPONSE_PATH}}` (use the Write tool). The report file must contain ONLY the report — start directly with the title or first finding, with no scratch-reasoning preamble, no "let me analyze" recap, and no truncation; include every finding in full. After writing the file, reply with a single short confirmation line (e.g. "Wrote N findings to response.md"). Your reply text is NOT the report — the saved file is.

IMPORTANT: Only work within {{WORKSPACE}}. The only path you may write outside it is `{{RESPONSE_PATH}}`.
