#!/usr/bin/env python3
"""Stamp tooling="disabled" onto every existing run that predates the tooling
dimension, so the schema is consistent. Idempotent: only adds the field when
missing. Updates both run_metadata.json and the run_metadata embedded inside
grading.json.

Usage: python3 scripts/backfill_tooling.py [--dry-run]
"""
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
RUNS = PROJ / "results" / "runs"


def patch(path, dry):
    try:
        data = json.loads(path.read_text())
    except Exception:
        return 0
    changed = 0
    # top-level run_metadata.json
    if "tooling" not in data and "skill" in data and "eval_id" in data:
        data["tooling"] = "disabled"
        changed = 1
    # grading.json embeds run_metadata
    rm = data.get("run_metadata")
    if isinstance(rm, dict) and "tooling" not in rm:
        rm["tooling"] = "disabled"
        changed = 1
    if changed and not dry:
        path.write_text(json.dumps(data, indent=2))
    return changed


def main():
    dry = "--dry-run" in sys.argv
    n = 0
    for f in RUNS.rglob("run_metadata.json"):
        n += patch(f, dry)
    for f in RUNS.rglob("grading.json"):
        n += patch(f, dry)
    print(f"{'[dry-run] would patch' if dry else 'patched'} {n} files with tooling=disabled")


if __name__ == "__main__":
    main()
