#!/usr/bin/env python3
"""Set up a SECOND identical Sonnet/no-tools pass over the 27 core_subset evals
x 6 skills, to measure the multi-pass effect (does combining independent passes
catch more bugs). One cell per file. run_metadata tagged pass=2, tooling=disabled.

Emits cfg_pass2.json {dir, n} for the workflow.
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRATCH = Path("/private/tmp/claude-501/-Users-elliott-dev-solidity-skill-benchmark/02e0cd49-0bf6-4ff7-afe2-8ca964942215/scratchpad")
MODEL = "claude-sonnet-4-6"

SKILLS = ["scv-scan", "ethskills/audit", "ethskills/security",
          "pashov-skills/solidity-auditor", "sc-auditor/security-auditor",
          "qs_skills/behavioral-state-analysis"]
EVALS = [e["eval_id"] for e in json.loads(
    (PROJ / "evals" / "core_subset.json").read_text())["evals"]]
skills_json = json.loads((PROJ / "skills.json").read_text())["skills"]


def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "P2"
    cells_dir = SCRATCH / "cells_pass2"
    cells_dir.mkdir(parents=True, exist_ok=True)
    cells = []
    i = 0
    for skill in SKILLS:
        skill_md = skills_json[skill]["path"]
        skill_src = PROJ / os.path.dirname(skill_md)
        dir_name = skill.replace("/", "__")
        for ev in EVALS:
            contracts_src = PROJ / "evals" / ev / "contracts"
            run_dir = PROJ / "results" / "runs" / dir_name / ev / ts
            run_dir.mkdir(parents=True, exist_ok=True)
            ws = Path(tempfile.mkdtemp(prefix=f"pass2_{dir_name}_{ev}_"))
            shutil.copytree(skill_src, ws / "skill")
            shutil.copytree(contracts_src, ws / "contracts")
            assert not (ws / "contracts" / "findings.json").exists()
            meta = {"skill": skill, "skill_path": skill_md, "eval_id": ev,
                    "timestamp": ts, "is_baseline": False, "model": MODEL,
                    "tooling": "disabled", "pass": 2}
            (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
            cell = {"skill": skill, "skillDirName": dir_name, "evalId": ev,
                    "workspace": str(ws), "contractsPath": str(ws / "contracts"),
                    "runDir": str(run_dir),
                    "responsePath": str(run_dir / "response.md"),
                    "gradingPath": str(run_dir / "grading.json"),
                    "findingsPath": str(PROJ / "evals" / ev / "findings.json")}
            (cells_dir / f"cell_{i}.json").write_text(json.dumps(cell, indent=2))
            cells.append(cell)
            i += 1
    cfg = {"dir": str(cells_dir), "n": i, "model": MODEL, "ts": ts}
    (SCRATCH / "cfg_pass2.json").write_text(json.dumps(cfg))
    print(f"Created {i} pass-2 cells ({len(SKILLS)} skills x {len(EVALS)} evals), TS={ts}")
    print(f"cfg -> {SCRATCH / 'cfg_pass2.json'}")


if __name__ == "__main__":
    main()
