# Auditor Subagent

This file is a reference for the orchestrating agent. It describes how to prepare a workspace and spawn an auditor subagent.

## When to spawn

Spawn one auditor subagent per (skill, eval) pair. Multiple auditors can run in parallel for different evals.

## Workspace setup

Before spawning the subagent, the orchestrating agent must create an isolated workspace directory containing the files the auditor needs. This is critical — the subagent needs real files on disk so it can use any tool (Read, Grep, Glob, Bash, etc.) including running scripts or tools that the skill might reference.

### Step 1: Create the workspace

```bash
WORKSPACE=$(mktemp -d /tmp/eval_XXXXXX)
```

### Step 2: Copy the full skill directory

Copy the entire skill directory (not just SKILL.md) so that reference files, scripts, and any other bundled resources are available:

```bash
# e.g., for scv-scan, copy skills/scv-scan/ → $WORKSPACE/skill/
cp -r <skill_directory>/ $WORKSPACE/skill/
```

The skill directory is the parent of the SKILL.md file. For example, if the SKILL.md is at `skills/scv-scan/SKILL.md`, copy `skills/scv-scan/` to `$WORKSPACE/skill/`.

For baseline runs (no skill), skip this step.

### Step 3: Copy the contracts

```bash
cp -r evals/<eval_id>/contracts/ $WORKSPACE/contracts/
```

**Never copy findings.json or metadata.json** — the auditor must not see ground truth.

### Resulting workspace layout

```
$WORKSPACE/
├── skill/              # Full skill directory (SKILL.md + references/, scripts/, etc.)
│   ├── SKILL.md
│   ├── references/     # If the skill has them
│   └── scripts/        # If the skill has them
└── contracts/          # Solidity files to audit
    ├── Contract1.sol
    ├── Contract2.sol
    └── ...
```

## How to build the prompt

The prompt tells the subagent where files are and what to do. It should reference paths relative to the workspace.

### Prompt template

```
You are performing a security audit of Solidity smart contracts.

Your working directory is {WORKSPACE}.

{IF_NOT_BASELINE}
## Your Audit Methodology

Read and follow the skill instructions at `skill/SKILL.md`. This defines your audit methodology, including any reference files or scripts you should use. All skill resources (references, scripts, etc.) are in the `skill/` directory.
{END_IF}

{IF_BASELINE}
## Your Audit Approach

You have no specific methodology to follow. Use your best judgment to audit the contracts.
{END_IF}

## Contracts to Audit

The Solidity contracts to audit are in the `contracts/` directory:
{FILE_LIST}

## Task

Read and analyze each contract. Identify all security vulnerabilities you can find. For each vulnerability, provide:

1. **Title** — A clear, descriptive name
2. **Severity** — Critical, High, Medium, Low, or Informational
3. **Description** — What the vulnerability is and why it matters
4. **Location** — The affected file(s) and function(s)/line(s)
5. **Recommendation** — How to fix it

Focus on real, exploitable vulnerabilities — not gas optimizations, style issues, or informational notes. Be thorough and systematic.

IMPORTANT: Only work within {WORKSPACE}. Do not access files outside this directory.
```

## Subagent configuration

- **subagent_type**: omit (use default general-purpose agent — it has access to all tools including Bash, Read, Write, Glob, Grep)
- **model**: use `sonnet` for cost efficiency, or match the model being benchmarked
- **description**: `"Audit {eval_id} with {skill_name}"`
- **prompt**: The filled-in template above

## What to do with the result

The subagent returns its audit findings as text. Save this to:
```
results/runs/{skill_dir_name}/{eval_id}/{timestamp}/response.md
```

Also save `run_metadata.json` with:
```json
{
  "skill": "<skill_name>",
  "skill_path": "<relative path to SKILL.md>",
  "eval_id": "<eval_id>",
  "timestamp": "<YYYYMMDDTHHMMSS>",
  "is_baseline": false,
  "model": "<model used>"
}
```

## Cleanup

After saving the result, remove the temp workspace:
```bash
rm -rf $WORKSPACE
```
