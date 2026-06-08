#!/usr/bin/env bash
#
# Run a single skill (or baseline) against a single eval.
#
# Usage:
#   ./scripts/run_eval.sh <skill_name_or_path> <eval_id> [--skip-if-exists]
#   ./scripts/run_eval.sh --baseline <eval_id> [--skip-if-exists]
#
# The first argument can be:
#   - A skill name from skills.json (e.g. "scv-scan", "pashov/solidity-auditor")
#   - A direct path to a SKILL.md file (e.g. skills/scv-scan/SKILL.md)
#   - --baseline (no skill)
#
# Skills are loaded by creating a temporary .claude/skills/ directory
# structure that Claude auto-discovers. The baseline runs with no skill.
#
# The skill receives ONLY the contract source files — never findings.
#
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$PROJ_ROOT/skills.json"

resolve_skill() {
    # Given a skill name or path, set SKILL_NAME and SKILL_PATH.
    local arg="$1"

    # If it's a file path that exists, derive name from the manifest or path
    if [ -f "$arg" ]; then
        SKILL_PATH="$(cd "$(dirname "$arg")" && pwd)/$(basename "$arg")"
        # Try to find a matching name in skills.json
        if [ -f "$MANIFEST" ]; then
            local rel_path
            rel_path="$(python3 -c "import os; print(os.path.relpath('$SKILL_PATH', '$PROJ_ROOT'))")"
            local found_name
            found_name="$(python3 -c "
import json, sys
with open('$MANIFEST') as f:
    m = json.load(f)
for name, info in m['skills'].items():
    if info['path'] == '$rel_path':
        print(name)
        sys.exit(0)
# Not in manifest — derive from path
parts = '$rel_path'.replace('skills/', '', 1).replace('/SKILL.md', '').split('/')
generic = {'skills', 'plugins'}
meaningful = [p for p in parts if p not in generic]
if len(meaningful) >= 2:
    print(f'{meaningful[0]}/{meaningful[-1]}')
elif meaningful:
    print(meaningful[0])
else:
    print('unknown')
" 2>/dev/null)" || true
            SKILL_NAME="${found_name:-unknown}"
        else
            # No manifest — derive from directory structure
            local rel_path
            rel_path="$(python3 -c "import os; print(os.path.relpath('$SKILL_PATH', '$PROJ_ROOT/skills'))")"
            SKILL_NAME="$(echo "$rel_path" | sed 's|/SKILL\.md$||' | sed 's|/skills/|/|g' | sed 's|/plugins/|/|g')"
        fi
        return
    fi

    # Otherwise treat as a skill name — look up in manifest
    if [ -f "$MANIFEST" ]; then
        local resolved
        resolved="$(python3 -c "
import json, sys
with open('$MANIFEST') as f:
    m = json.load(f)
name = '$arg'
if name in m['skills']:
    print(m['skills'][name]['path'])
    sys.exit(0)
# Try partial match
for k, v in m['skills'].items():
    if name in k or k in name:
        print(v['path'])
        sys.exit(0)
print('')
" 2>/dev/null)" || true

        if [ -n "$resolved" ] && [ -f "$PROJ_ROOT/$resolved" ]; then
            SKILL_NAME="$arg"
            SKILL_PATH="$PROJ_ROOT/$resolved"
            return
        fi
    fi

    echo "Error: '$arg' is not a file and was not found in skills.json"
    echo "  Run: python3 scripts/discover_skills.py --update"
    exit 1
}

# Parse args
BASELINE=false
if [ "$1" = "--baseline" ]; then
    BASELINE=true
    SKILL_NAME="baseline"
    EVAL_ID="$2"
    SKIP_IF_EXISTS="${3:-}"
else
    resolve_skill "$1"
    EVAL_ID="$2"
    SKIP_IF_EXISTS="${3:-}"

    if [ ! -f "$SKILL_PATH" ]; then
        echo "Error: Skill file not found: $SKILL_PATH"
        exit 1
    fi
fi

EVAL_DIR="$PROJ_ROOT/evals/$EVAL_ID"
TIMESTAMP="$(date +%Y%m%dT%H%M%S)"

# Sanitize skill name for filesystem (replace / with __)
SKILL_DIR_NAME="$(echo "$SKILL_NAME" | sed 's|/|__|g')"
RUN_DIR="$PROJ_ROOT/results/runs/$SKILL_DIR_NAME/$EVAL_ID/$TIMESTAMP"

if [ ! -d "$EVAL_DIR/contracts" ]; then
    echo "Error: No contracts found at $EVAL_DIR/contracts"
    exit 1
fi

# Optional: skip if we already have a run for this skill+eval
if [ "$SKIP_IF_EXISTS" = "--skip-if-exists" ]; then
    EXISTING="$PROJ_ROOT/results/runs/$SKILL_NAME/$EVAL_ID"
    if [ -d "$EXISTING" ] && [ "$(ls -A "$EXISTING" 2>/dev/null)" ]; then
        echo "Skipping $SKILL_NAME/$EVAL_ID (already exists)"
        exit 0
    fi
fi

mkdir -p "$RUN_DIR"

# Create a temporary workspace with the contracts and optional skill
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

# Copy contracts into the workspace
mkdir -p "$WORKDIR/contracts"
cp "$EVAL_DIR/contracts"/*.sol "$WORKDIR/contracts/"

# If not baseline, install the skill into the workspace's .claude/skills/
if [ "$BASELINE" = false ]; then
    mkdir -p "$WORKDIR/.claude/skills/$SKILL_NAME"
    cp "$SKILL_PATH" "$WORKDIR/.claude/skills/$SKILL_NAME/SKILL.md"
fi

# Build the prompt: just the contract file paths
CONTRACT_LIST=""
for sol_file in "$WORKDIR/contracts"/*.sol; do
    if [ -f "$sol_file" ]; then
        CONTRACT_LIST="$CONTRACT_LIST  - contracts/$(basename "$sol_file")\n"
    fi
done

PROMPT="You are performing a security audit of the following Solidity smart contract(s). Read each file, then identify all vulnerabilities you can find. For each vulnerability, provide:
1. A clear title
2. Severity (Critical/High/Medium/Low/Informational)
3. Description of the vulnerability
4. The affected file(s) and line(s)
5. Recommended fix

Be thorough. Focus on real, exploitable vulnerabilities — not gas optimizations or style issues.

Contract files to audit:
$(echo -e "$CONTRACT_LIST")"

echo "Running $SKILL_NAME against $EVAL_ID..."
START_TIME=$(date +%s)

# Run claude from the workspace directory so it discovers the skill
# --max-turns 3: enough to read files and respond
# --output-format json: structured output for parsing
# --allowedTools: pre-approve Read so it can read the contracts without prompting
cd "$WORKDIR"
claude -p "$PROMPT" \
    --output-format json \
    --max-turns 5 \
    --allowedTools "Read,Glob,Grep" \
    > "$RUN_DIR/raw_response.json" 2>"$RUN_DIR/stderr.log" || true
cd "$PROJ_ROOT"

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Extract response text and build run metadata from claude's JSON output
SKILL_PATH_REL=""
if [ "$BASELINE" = false ]; then
    SKILL_PATH_REL="$(python3 -c "import os; print(os.path.relpath('$SKILL_PATH', '$PROJ_ROOT'))")"
fi

python3 -c "
import json, sys

run_dir = '$RUN_DIR'
raw_path = f'{run_dir}/raw_response.json'

try:
    with open(raw_path) as f:
        data = json.load(f)
except Exception as e:
    print(f'Warning: Could not parse raw response: {e}', file=sys.stderr)
    data = {}

# --- Extract response text ---
text = ''
if isinstance(data, dict):
    text = data.get('result', data.get('response', json.dumps(data, indent=2)))
elif isinstance(data, list):
    parts = [b.get('text', '') for b in data if isinstance(b, dict) and b.get('type') == 'text']
    text = '\n'.join(parts) if parts else json.dumps(data, indent=2)
else:
    text = str(data)

with open(f'{run_dir}/response.md', 'w') as f:
    f.write(text)

# --- Build run metadata ---
usage = data.get('usage', {}) if isinstance(data, dict) else {}
model_usage = data.get('modelUsage', {}) if isinstance(data, dict) else {}

# Flatten model info: pick the first (usually only) model entry
model_name = ''
model_info = {}
if model_usage:
    model_name = next(iter(model_usage))
    model_info = model_usage[model_name]

metadata = {
    'skill': '$SKILL_NAME',
    'skill_path': '$SKILL_PATH_REL',
    'eval_id': '$EVAL_ID',
    'timestamp': '$TIMESTAMP',
    'is_baseline': $( [ \"\$BASELINE\" = true ] && echo 'True' || echo 'False' ),

    # Timing
    'duration_seconds': $DURATION,
    'duration_ms': data.get('duration_ms', 0) if isinstance(data, dict) else 0,
    'duration_api_ms': data.get('duration_api_ms', 0) if isinstance(data, dict) else 0,
    'num_turns': data.get('num_turns', 0) if isinstance(data, dict) else 0,

    # Cost
    'total_cost_usd': data.get('total_cost_usd', 0) if isinstance(data, dict) else 0,

    # Model
    'model': model_name,

    # Token usage
    'tokens': {
        'input': model_info.get('inputTokens', usage.get('input_tokens', 0)),
        'output': model_info.get('outputTokens', usage.get('output_tokens', 0)),
        'cache_read': model_info.get('cacheReadInputTokens', usage.get('cache_read_input_tokens', 0)),
        'cache_creation': model_info.get('cacheCreationInputTokens',
                            usage.get('cache_creation_input_tokens', 0)),
    },
}

with open(f'{run_dir}/run_metadata.json', 'w') as f:
    json.dump(metadata, f, indent=2)

# Print summary
tokens = metadata['tokens']
total_tokens = tokens['input'] + tokens['output'] + tokens['cache_read'] + tokens['cache_creation']
print(f'  Model: {model_name}')
print(f'  Tokens: {total_tokens:,} (in={tokens[\"input\"]:,} out={tokens[\"output\"]:,} cache_read={tokens[\"cache_read\"]:,} cache_create={tokens[\"cache_creation\"]:,})')
print(f'  Cost: \${metadata[\"total_cost_usd\"]:.4f}')
"

echo "Done: $RUN_DIR (${DURATION}s)"
