#!/usr/bin/env bash
#
# Run a skill (or baseline) against the core subset, then grade and aggregate.
#
# Usage:
#   ./scripts/run_benchmark.sh <skill_path>                          # run core subset
#   ./scripts/run_benchmark.sh --baseline                            # run baseline (no skill)
#   ./scripts/run_benchmark.sh <skill_path> --sample 5               # random 5 from core
#   ./scripts/run_benchmark.sh <skill_path> --evals vfp_00001,vfp_00002
#   ./scripts/run_benchmark.sh <skill_path> --all                    # all 300 evals
#   ./scripts/run_benchmark.sh <skill_path> --skip-if-exists         # skip already-run evals
#
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Parse first arg: skill path, skill name, or --baseline
BASELINE=false
SKILL_ARG=""
MANIFEST="$PROJ_ROOT/skills.json"

if [ "$1" = "--baseline" ]; then
    BASELINE=true
    SKILL_ARG="--baseline"
    SKILL_NAME="baseline"
    shift
else
    SKILL_ARG="$1"
    # Resolve skill name: use the same logic as run_eval.sh
    # If it's a file, derive name from manifest or path structure
    if [ -f "$1" ]; then
        SKILL_PATH_ABS="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
        if [ -f "$MANIFEST" ]; then
            REL_PATH="$(python3 -c "import os; print(os.path.relpath('$SKILL_PATH_ABS', '$PROJ_ROOT'))")"
            SKILL_NAME="$(python3 -c "
import json, sys
with open('$MANIFEST') as f:
    m = json.load(f)
for name, info in m['skills'].items():
    if info['path'] == '$REL_PATH':
        print(name); sys.exit(0)
parts = '$REL_PATH'.replace('skills/', '', 1).replace('/SKILL.md', '').split('/')
generic = {'skills', 'plugins'}
meaningful = [p for p in parts if p not in generic]
if len(meaningful) >= 2: print(f'{meaningful[0]}/{meaningful[-1]}')
elif meaningful: print(meaningful[0])
else: print('unknown')
" 2>/dev/null)" || SKILL_NAME="unknown"
        else
            SKILL_NAME="$(python3 -c "
import os
rel = os.path.relpath('$SKILL_PATH_ABS', '$PROJ_ROOT/skills')
parts = rel.replace('/SKILL.md', '').split('/')
generic = {'skills', 'plugins'}
meaningful = [p for p in parts if p not in generic]
if len(meaningful) >= 2: print(f'{meaningful[0]}/{meaningful[-1]}')
elif meaningful: print(meaningful[0])
else: print('unknown')
")"
        fi
    else
        # Assume it's a skill name from the manifest
        SKILL_NAME="$1"
    fi
    shift
fi

# Sanitize skill name for filesystem paths
SKILL_DIR_NAME="$(echo "$SKILL_NAME" | sed 's|/|__|g')"

SAMPLE=""
EVAL_LIST=""
SKIP_FLAG=""
USE_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --sample) SAMPLE="$2"; shift 2 ;;
        --evals) EVAL_LIST="$2"; shift 2 ;;
        --all) USE_ALL=true; shift ;;
        --skip-if-exists) SKIP_FLAG="--skip-if-exists"; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Build eval list
if [ -n "$EVAL_LIST" ]; then
    # Explicit list
    EVALS=(${EVAL_LIST//,/ })
elif [ "$USE_ALL" = true ]; then
    # All 300
    EVALS=($(ls "$PROJ_ROOT/evals" | grep "^vfp_"))
elif [ -n "$SAMPLE" ]; then
    # Random sample from core subset
    EVALS=($(python3 -c "
import json, random
with open('$PROJ_ROOT/evals/core_subset.json') as f:
    data = json.load(f)
ids = [e['eval_id'] for e in data['evals']]
random.shuffle(ids)
for eid in ids[:$SAMPLE]:
    print(eid)
"))
else
    # Default: full core subset
    EVALS=($(python3 -c "
import json
with open('$PROJ_ROOT/evals/core_subset.json') as f:
    data = json.load(f)
for e in data['evals']:
    print(e['eval_id'])
"))
fi

echo "=== Benchmark: $SKILL_NAME ==="
echo "Evals to run: ${#EVALS[@]}"
echo ""

COMPLETED=0
FAILED=0

for eval_id in "${EVALS[@]}"; do
    echo "[$((COMPLETED + FAILED + 1))/${#EVALS[@]}] $eval_id"

    # Run eval
    if python3 "$PROJ_ROOT/scripts/run_eval.py" "$SKILL_ARG" "$eval_id" $SKIP_FLAG; then
        # Find the run dir (most recent)
        RUN_DIR=$(ls -td "$PROJ_ROOT/results/runs/$SKILL_DIR_NAME/$eval_id"/*/ 2>/dev/null | head -1)

        if [ -n "$RUN_DIR" ] && [ -f "$RUN_DIR/response.md" ]; then
            # Grade it
            python3 "$PROJ_ROOT/scripts/grade.py" "$RUN_DIR" "$eval_id" || true
            COMPLETED=$((COMPLETED + 1))
        else
            echo "  Warning: No response found, skipping grading"
            FAILED=$((FAILED + 1))
        fi
    else
        FAILED=$((FAILED + 1))
    fi

    # Update skill_tracking in core_subset.json
    python3 -c "
import json
path = '$PROJ_ROOT/evals/core_subset.json'
with open(path) as f:
    data = json.load(f)
tracking = data.setdefault('skill_tracking', {})
if '$SKILL_NAME' not in tracking or tracking['$SKILL_NAME'] == []:
    tracking['$SKILL_NAME'] = []
if '$eval_id' not in tracking['$SKILL_NAME']:
    tracking['$SKILL_NAME'].append('$eval_id')
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
" 2>/dev/null || true

done

echo ""
echo "=== Completed: $COMPLETED, Failed: $FAILED ==="
echo ""

# Aggregate results
python3 "$PROJ_ROOT/scripts/aggregate.py"
