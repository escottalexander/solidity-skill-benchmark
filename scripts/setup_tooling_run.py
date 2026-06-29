#!/usr/bin/env python3
"""Set up the tooling A/B run: 6 skills x compilable evals x {disabled, enabled},
one cell per file. Model = sonnet (first pass).

- disabled cell: workspace/skill + workspace/contracts (raw source, no tools).
- enabled cell:  workspace/skill + workspace/project (a compiling Foundry
  project: src + lib symlinks + remappings + foundry.toml + slither.config.json).
Each eval is built once into a template, then each enabled cell copies src/config
and re-symlinks lib so concurrent slither runs don't clash on out/.

Emits cfg_tooling.json {dir, n} for the workflow.
"""
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import compile_eval as ce

PROJ = Path(__file__).resolve().parent.parent
SCRATCH = Path("/private/tmp/claude-501/-Users-elliott-dev-solidity-skill-benchmark/02e0cd49-0bf6-4ff7-afe2-8ca964942215/scratchpad")
MODEL = "claude-sonnet-4-6"
VENV_BIN = PROJ / ".venv-tools" / "bin"

SKILLS = ["scv-scan", "ethskills/audit", "ethskills/security",
          "pashov-skills/solidity-auditor", "sc-auditor/security-auditor",
          "qs_skills/behavioral-state-analysis"]
TSET = json.loads((PROJ / "evals" / "tooling_set.json").read_text())["evals"]
skills_json = json.loads((PROJ / "skills.json").read_text())["skills"]


def build_templates():
    """Build each compilable eval once into a reusable template project."""
    tpl_root = SCRATCH / "tpl"
    tpl_root.mkdir(parents=True, exist_ok=True)
    ok = {}
    for ev in TSET:
        dest = tpl_root / ev
        if (dest / "foundry.toml").exists():
            ok[ev] = dest
            continue
        st = ce.build_eval(ev, str(dest))
        if st["compiled"]:
            ok[ev] = dest
        else:
            print(f"  WARN template build failed for {ev}; skipping enabled arm")
    return ok


def make_enabled_project(tpl_dir, dest):
    """Copy a template project's src+config to dest, symlink lib fresh."""
    (dest).mkdir(parents=True)
    shutil.copytree(tpl_dir / "src", dest / "src")
    shutil.copy2(tpl_dir / "remappings.txt", dest / "remappings.txt")
    shutil.copy2(tpl_dir / "foundry.toml", dest / "foundry.toml")
    (dest / "lib").mkdir()
    for link in (tpl_dir / "lib").iterdir():
        os.symlink(os.path.realpath(link), dest / "lib" / link.name)
    # scope slither to our own sources, not the dependency libs
    (dest / "slither.config.json").write_text(
        json.dumps({"filter_paths": "lib/"}, indent=2))


def main():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    cells_dir = SCRATCH / "cells_tooling"
    cells_dir.mkdir(parents=True, exist_ok=True)
    print(f"Building {len(TSET)} eval templates for the enabled arm...")
    templates = build_templates()
    print(f"  {len(templates)}/{len(TSET)} templates ready")

    cells = []
    i = 0
    for skill in SKILLS:
        skill_md = skills_json[skill]["path"]
        skill_src = PROJ / os.path.dirname(skill_md)
        dir_name = skill.replace("/", "__")
        for ev in TSET:
            contracts_src = PROJ / "evals" / ev / "contracts"
            for arm in ("disabled", "enabled"):
                if arm == "enabled" and ev not in templates:
                    continue
                run_ts = f"{ts}{'D' if arm == 'disabled' else 'E'}"
                run_dir = PROJ / "results" / "runs" / dir_name / ev / run_ts
                run_dir.mkdir(parents=True, exist_ok=True)
                ws = Path(tempfile.mkdtemp(prefix=f"tool_{arm}_{dir_name}_{ev}_"))
                shutil.copytree(skill_src, ws / "skill")
                meta = {"skill": skill, "skill_path": skill_md, "eval_id": ev,
                        "timestamp": run_ts, "is_baseline": False, "model": MODEL,
                        "tooling": arm}
                cell = {"skill": skill, "skillDirName": dir_name, "evalId": ev,
                        "arm": arm, "workspace": str(ws), "runDir": str(run_dir),
                        "responsePath": str(run_dir / "response.md"),
                        "gradingPath": str(run_dir / "grading.json"),
                        "findingsPath": str(PROJ / "evals" / ev / "findings.json")}
                if arm == "disabled":
                    shutil.copytree(contracts_src, ws / "contracts")
                    cell["contractsPath"] = str(ws / "contracts")
                else:
                    make_enabled_project(templates[ev], ws / "project")
                    cell["projectPath"] = str(ws / "project")
                    cell["toolsBin"] = str(VENV_BIN)
                    meta["tools_available"] = ["slither", "halmos", "forge"]
                    cell["contractFiles"] = sorted(
                        f.name for f in contracts_src.rglob("*.sol"))
                (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))
                (cells_dir / f"cell_{i}.json").write_text(json.dumps(cell, indent=2))
                cells.append(cell)
                i += 1

    cfg = {"dir": str(cells_dir), "n": i, "model": MODEL, "ts": ts}
    (SCRATCH / "cfg_tooling.json").write_text(json.dumps(cfg))
    n_dis = sum(1 for c in cells if c["arm"] == "disabled")
    n_en = sum(1 for c in cells if c["arm"] == "enabled")
    print(f"Created {i} cells ({n_dis} disabled, {n_en} enabled), TS={ts}")
    print(f"cfg -> {SCRATCH / 'cfg_tooling.json'}")


if __name__ == "__main__":
    main()
