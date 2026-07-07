#!/usr/bin/env python3
"""Verify the security-audit toolchain and report tool versions.

Used two ways:
- CLI sanity check before a tooling-enabled run:  python3 scripts/check_tooling.py
- Imported by prepare_run.py to record exact tool versions in run_metadata.json,
  so every tooling run documents precisely which tool versions the auditor had.

Search order per tool: the repo venv (.venv-tools/bin), then PATH (covers
~/.foundry/bin and ~/.cargo/bin if the user's shell profile adds them).

Exit non-zero if a REQUIRED tool is missing (forge + slither are the minimum
for a valid tooling arm; the rest are reported but optional).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
VENV_BIN = PROJ / ".venv-tools" / "bin"
EXTRA_PATHS = [str(VENV_BIN), str(Path.home() / ".foundry" / "bin"),
               str(Path.home() / ".cargo" / "bin"),
               "/opt/homebrew/bin", "/usr/local/bin"]

# tool -> version argv
TOOLS = {
    "forge": ["--version"],
    "cast": ["--version"],
    "slither": ["--version"],
    "crytic-compile": ["--version"],
    "semgrep": ["--version"],
    "aderyn": ["--version"],
    "echidna": ["--version"],
    "medusa": ["--version"],
    "halmos": ["--version"],
    "solc-select": ["versions"],
    "solhint": ["--version"],
}
REQUIRED = {"forge", "slither"}


def _find(tool):
    for p in EXTRA_PATHS:
        cand = Path(p) / tool
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return shutil.which(tool)


def get_tool_versions(tools=None) -> dict:
    """{tool: {"path": str, "version": str}} for every available tool."""
    out = {}
    for tool, args in TOOLS.items():
        if tools and tool not in tools:
            continue
        path = _find(tool)
        if not path:
            continue
        try:
            r = subprocess.run([path] + args, capture_output=True, text=True,
                               timeout=60)
            ver = (r.stdout or r.stderr).strip().splitlines()
            out[tool] = {"path": path, "version": ver[0][:120] if ver else "?"}
        except Exception as e:
            out[tool] = {"path": path, "version": f"ERROR: {e}"}
    return out


def main():
    vers = get_tool_versions()
    print(json.dumps(vers, indent=2))
    missing_req = REQUIRED - set(vers)
    missing_opt = set(TOOLS) - set(vers) - REQUIRED
    if missing_opt:
        print(f"\noptional tools missing: {sorted(missing_opt)}", file=sys.stderr)
    if missing_req:
        print(f"REQUIRED tools missing: {sorted(missing_req)}", file=sys.stderr)
        sys.exit(1)
    print(f"\nOK: {len(vers)}/{len(TOOLS)} tools available "
          f"(required: {sorted(REQUIRED)} all present)", file=sys.stderr)


if __name__ == "__main__":
    main()
