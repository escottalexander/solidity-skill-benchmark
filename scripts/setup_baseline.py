#!/usr/bin/env python3
"""Set up the no-skill BASELINE: how well does the raw model audit with no skill
methodology? Sonnet AND Opus, on the same 27 core_subset evals, source-only.

54 cells (27 evals x 2 models). Workspace has ONLY contracts (no skill dir).
run_metadata: skill="baseline", is_baseline=true, model, tooling=disabled.
Emits cfg_baseline.json {dir, n, models} (models[i] = model for cell i).
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRATCH = Path("/private/tmp/claude-501/-Users-elliott-dev-solidity-skill-benchmark/02e0cd49-0bf6-4ff7-afe2-8ca964942215/scratchpad")
MODELS = {"sonnet": "claude-sonnet-4-6", "opus": "claude-opus-4-8"}
EVALS = [e["eval_id"] for e in json.loads(
    (PROJ / "evals" / "core_subset.json").read_text())["evals"]]


def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    cells_dir = SCRATCH / "cells_baseline"
    cells_dir.mkdir(parents=True, exist_ok=True)
    models = []
    i = 0
    for short, model_id in MODELS.items():
        for ev in EVALS:
            contracts_src = PROJ / "evals" / ev / "contracts"
            run_ts = f"{ts}B{short}"
            run_dir = PROJ / "results" / "runs" / "baseline" / ev / run_ts
            run_dir.mkdir(parents=True, exist_ok=True)
            ws = Path(tempfile.mkdtemp(prefix=f"base_{short}_{ev}_"))
            shutil.copytree(contracts_src, ws / "contracts")
            assert not (ws / "contracts" / "findings.json").exists()
            meta = {"skill": "baseline", "skill_path": "", "eval_id": ev,
                    "timestamp": run_ts, "is_baseline": True, "model": model_id,
                    "tooling": "disabled"}
            (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
            cell = {"skill": "baseline", "skillDirName": "baseline", "evalId": ev,
                    "model": model_id, "workspace": str(ws),
                    "contractsPath": str(ws / "contracts"), "runDir": str(run_dir),
                    "responsePath": str(run_dir / "response.md"),
                    "gradingPath": str(run_dir / "grading.json"),
                    "findingsPath": str(PROJ / "evals" / ev / "findings.json")}
            (cells_dir / f"cell_{i}.json").write_text(json.dumps(cell, indent=2))
            models.append(model_id)
            i += 1
    cfg = {"dir": str(cells_dir), "n": i, "models": models, "ts": ts}
    (SCRATCH / "cfg_baseline.json").write_text(json.dumps(cfg))
    print(f"Created {i} baseline cells (27 evals x 2 models), TS={ts}")
    print(f"cfg -> {SCRATCH / 'cfg_baseline.json'}")


if __name__ == "__main__":
    main()
