#!/usr/bin/env bash
# Install the static-analysis / symbolic / fuzzing tool suite for the
# tooling-enabled benchmark arm. Slither is essential (verified working);
# the rest are best-effort and the script reports what succeeded.
#
# Usage: bash scripts/setup_tooling.sh
# Prints the absolute tool paths the auditor prompt should reference.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv-tools"

echo "== creating venv at $VENV =="
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1

echo "== installing Slither (essential) =="
"$VENV/bin/pip" install --quiet slither-analyzer && echo "  slither: $($VENV/bin/slither --version 2>&1 | head -1)"

echo "== installing Mythril (best-effort) =="
"$VENV/bin/pip" install --quiet mythril 2>/dev/null && echo "  myth: $($VENV/bin/myth version 2>&1 | head -1)" || echo "  mythril: SKIPPED (install failed on this Python)"

echo "== installing Halmos (best-effort) =="
"$VENV/bin/pip" install --quiet halmos 2>/dev/null && echo "  halmos: $($VENV/bin/halmos --version 2>&1 | head -1)" || echo "  halmos: SKIPPED"

echo "== installing Aderyn via cargo (best-effort) =="
if command -v cargo >/dev/null 2>&1; then
  cargo install aderyn --quiet 2>/dev/null && echo "  aderyn: $(aderyn --version 2>&1 | head -1)" || echo "  aderyn: SKIPPED (cargo install failed)"
else
  echo "  aderyn: SKIPPED (no cargo)"
fi

echo "== Foundry (forge/cast) — expected already present =="
command -v forge >/dev/null 2>&1 && echo "  forge: $(forge --version | head -1)" || echo "  forge: MISSING"

echo ""
echo "== Tool paths for the enabled-arm prompt =="
echo "  slither: $VENV/bin/slither"
echo "  myth:    $VENV/bin/myth   (if installed)"
echo "  halmos:  $VENV/bin/halmos (if installed)"
echo "  aderyn:  $(command -v aderyn 2>/dev/null || echo '~/.cargo/bin/aderyn (if installed)')"
echo "  forge:   $(command -v forge)"
