#!/usr/bin/env python3
"""Deterministic run preparation for benchmark experiments.

This replaces ad-hoc orchestrator workspace/prompt construction. It owns
EVERYTHING except the actual model calls:

  1. isolated workspace per cell (skill dir + contracts, or a compiling
     Foundry project for tooling-enabled runs) — asserts ground truth is absent
  2. run directory + run_metadata.json with full provenance: prompt template
     versions, skill-directory content hash, contracts content hash, tool
     versions (tooling arm), experiment name, rep number
  3. the EXACT auditor + grader prompts, rendered from the frozen templates in
     agents/prompts/ and saved as prompt.md / grader_prompt.md in the run dir
  4. one cell_<i>.json per cell for the Workflow tool (one-cell-per-file rule)
  5. an experiment manifest in results/experiments/<name>.json listing every
     cell, so aggregation selects runs explicitly instead of by directory-name
     heuristics

The orchestrator/workflow then spawns each auditor with the cell's
"auditorBootstrap" string verbatim (and the grader with "graderBootstrap") —
no hand-written prompts anywhere.

Usage:
  python3 scripts/prepare_run.py --experiment sonnet-rep3 \
      --skills scv-scan ethskills/audit baseline \
      --eval-set core_subset --model claude-sonnet-4-6 \
      --tooling disabled --reps 3
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import render_prompt as rp          # noqa: E402
import check_tooling as ct          # noqa: E402

PROJ = SCRIPTS.parent
PROMPTS_DIR = PROJ / "agents" / "prompts"
RUNS_DIR = PROJ / "results" / "runs"
EXP_DIR = PROJ / "results" / "experiments"
CACHE = PROJ / ".cache"

BOOTSTRAP = ("Read the file {path} with the Read tool, then follow its "
             "instructions exactly. That file is your complete task "
             "specification; do not deviate from it, and do not read any other "
             "file outside the locations it names.")

FORBIDDEN = {"findings.json", "metadata.json"}


def sha256_dir(root) -> str:
    """Content hash of a directory: sha256 over sorted (relpath, file-sha)."""
    root = Path(root)
    h = hashlib.sha256()
    for f in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(root)).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16]


def load_eval_ids(args) -> list:
    if args.evals:
        return list(args.evals)
    path = PROJ / "evals" / f"{args.eval_set}.json"
    data = json.loads(path.read_text())
    entries = data["evals"] if isinstance(data, dict) else data
    return [e if isinstance(e, str) else e["eval_id"] for e in entries]


def contract_rel_paths(eval_id) -> list:
    base = PROJ / "evals" / eval_id / "contracts"
    return sorted(str(p.relative_to(base)) for p in base.rglob("*.sol"))


def assert_no_ground_truth(workspace):
    hits = [p for p in Path(workspace).rglob("*")
            if p.is_file() and p.name in FORBIDDEN]
    if hits:
        raise RuntimeError(f"ground truth leaked into workspace: {hits}")


# ---------- tooling arm ----------

def build_tooling_template(eval_id):
    """Return (template_path, kind) for a compiling project, or None.

    kind "repo":     fresh eval imported from a real audited repo
                     (evals/<id>/project_lock.json) — the pinned clone in
                     .cache/imports/<id>/repo IS the template.
    kind "scaffold": legacy vfp_* partial snapshot rebuilt into a compiling
                     Foundry project by compile_eval.py.
    """
    lock_p = PROJ / "evals" / eval_id / "project_lock.json"
    if lock_p.exists():
        lock = json.loads(lock_p.read_text())
        repo = CACHE / "imports" / eval_id / "repo"
        if not (repo / ".git").exists():
            import import_recent_audit as ira
            print(f"  re-cloning {eval_id} at pinned commit...")
            ira.clone_at_commit(lock["repo_url"], lock["commit"], repo)
        if lock.get("project_subdir") not in (None, "", "."):
            repo = repo / lock["project_subdir"]
        if not (repo / "foundry.toml").exists():
            return None
        return repo, "repo"

    os.environ.setdefault("TOOLING_SCRATCH", str(CACHE / "tooling"))
    import compile_eval as ce
    if not (ce.LIB_CACHE / "oz-v5").exists():
        print("  setting up dependency lib cache (one-time)...")
        ce.setup_cache()
    dest = CACHE / "tooling" / "tpl" / eval_id
    if (dest / "foundry.toml").exists():
        return dest, "scaffold"
    st = ce.build_eval(eval_id, str(dest))
    if not st["compiled"]:
        return None
    return dest, "scaffold"


_REPO_SKIP = {".git", "out", "cache", "broadcast", "lib", "node_modules"}


def make_enabled_project(tpl, dest):
    """Materialize a per-cell project from a template: copy sources/config,
    symlink lib fresh (so concurrent tool runs don't clash on build artifacts)."""
    tpl_dir, kind = tpl
    dest = Path(dest)
    if kind == "scaffold":
        dest.mkdir(parents=True)
        shutil.copytree(tpl_dir / "src", dest / "src")
        shutil.copy2(tpl_dir / "remappings.txt", dest / "remappings.txt")
        shutil.copy2(tpl_dir / "foundry.toml", dest / "foundry.toml")
        (dest / "lib").mkdir()
        for link in (tpl_dir / "lib").iterdir():
            os.symlink(os.path.realpath(link), dest / "lib" / link.name)
    else:  # full repo clone
        shutil.copytree(tpl_dir, dest,
                        ignore=lambda d, names: [n for n in names
                                                 if n in _REPO_SKIP])
        if (tpl_dir / "lib").is_dir():
            (dest / "lib").mkdir()
            for sub in (tpl_dir / "lib").iterdir():
                os.symlink(os.path.realpath(sub), dest / "lib" / sub.name)
    if not (dest / "slither.config.json").exists():
        (dest / "slither.config.json").write_text(
            json.dumps({"filter_paths": "lib/"}, indent=2))


def tool_env():
    vers = ct.get_tool_versions()
    missing = ct.REQUIRED - set(vers)
    if missing:
        raise RuntimeError(f"tooling run requested but required tools missing: "
                           f"{sorted(missing)} — run scripts/check_tooling.py")
    bin_dirs = []
    for v in vers.values():
        d = str(Path(v["path"]).parent)
        if d not in bin_dirs:
            bin_dirs.append(d)
    tool_lines = "\n".join(f"- {name}: {v['version']}"
                           for name, v in sorted(vers.items()))
    return vers, ":".join(bin_dirs), tool_lines


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True,
                    help="experiment name (manifest results/experiments/<name>.json)")
    ap.add_argument("--skills", nargs="+", required=True,
                    help="skill names from skills.json, and/or 'baseline'")
    ap.add_argument("--evals", nargs="*", help="explicit eval ids")
    ap.add_argument("--eval-set", default="core_subset",
                    help="evals/<name>.json registry (default core_subset)")
    ap.add_argument("--model", required=True,
                    help="full model id, e.g. claude-sonnet-4-6")
    ap.add_argument("--tooling", choices=["disabled", "enabled"],
                    default="disabled")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing experiment manifest")
    args = ap.parse_args()

    manifest_path = EXP_DIR / f"{args.experiment}.json"
    if manifest_path.exists() and not args.force:
        sys.exit(f"experiment '{args.experiment}' already exists "
                 f"({manifest_path}); pick a new name or --force")

    skills_json = json.loads((PROJ / "skills.json").read_text())["skills"]
    for s in args.skills:
        if s != "baseline" and s not in skills_json:
            sys.exit(f"unknown skill: {s} (not in skills.json)")

    eval_ids = load_eval_ids(args)
    for ev in eval_ids:
        if not (PROJ / "evals" / ev / "contracts").is_dir():
            sys.exit(f"eval {ev} has no contracts/ directory")

    tool_versions, tools_bin, tool_lines = ({}, "", "")
    templates = {}
    if args.tooling == "enabled":
        tool_versions, tools_bin, tool_lines = tool_env()
        print(f"tooling: {len(tool_versions)} tools available")
        print(f"building/reusing compile templates for {len(eval_ids)} evals...")
        for ev in eval_ids:
            tpl = build_tooling_template(ev)
            if tpl is None:
                print(f"  WARN {ev} does not compile; excluded from this experiment")
            else:
                templates[ev] = tpl
        eval_ids = [e for e in eval_ids if e in templates]
        if not eval_ids:
            sys.exit("no evals compiled; nothing to prepare")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    cells_dir = CACHE / "experiments" / args.experiment / "cells"
    if cells_dir.exists():
        shutil.rmtree(cells_dir)
    cells_dir.mkdir(parents=True)

    skill_sha_cache, contracts_sha_cache = {}, {}
    aud_tpl_name = (f"auditor_{'tooling' if args.tooling == 'enabled' else 'source'}"
                    f"{{baseline}}.md")
    grader_tpl = PROMPTS_DIR / "grader.md"

    cells, manifest_cells = [], []
    i = 0
    for skill in args.skills:
        is_baseline = skill == "baseline"
        dir_name = "baseline" if is_baseline else skill.replace("/", "__")
        skill_md = "" if is_baseline else skills_json[skill]["path"]
        skill_src = None if is_baseline else PROJ / os.path.dirname(skill_md)
        if not is_baseline and skill not in skill_sha_cache:
            skill_sha_cache[skill] = sha256_dir(skill_src)

        for ev in eval_ids:
            if ev not in contracts_sha_cache:
                contracts_sha_cache[ev] = sha256_dir(PROJ / "evals" / ev / "contracts")
            rels = contract_rel_paths(ev)

            for rep in range(1, args.reps + 1):
                run_ts = f"{ts}r{rep}"
                run_dir = RUNS_DIR / dir_name / ev / run_ts
                if run_dir.exists():
                    sys.exit(f"run dir already exists: {run_dir}")
                run_dir.mkdir(parents=True)
                # workspaces live in the repo cache, NOT system tmp: macOS
                # purges /var/folders files within hours, which hollowed out
                # 88 workspaces during a stalled 2026-07-05 run
                ws = CACHE / "workspaces" / args.experiment / f"ws_{i}"
                ws.mkdir(parents=True)

                if not is_baseline:
                    shutil.copytree(skill_src, ws / "skill")

                mapping = {"WORKSPACE": str(ws),
                           "RESPONSE_PATH": str(run_dir / "response.md")}
                if args.tooling == "disabled":
                    shutil.copytree(PROJ / "evals" / ev / "contracts",
                                    ws / "contracts")
                    mapping["FILE_LIST"] = "\n".join(f"- contracts/{r}" for r in rels)
                else:
                    make_enabled_project(templates[ev], ws / "project")
                    # scaffold evals: contracts/ rel paths were copied under
                    # src/; repo evals: contracts/ already holds repo-relative
                    # paths (src/..., contracts/...)
                    prefix = ("project/" if templates[ev][1] == "repo"
                              else "project/src/")
                    mapping["FILE_LIST"] = "\n".join(f"- {prefix}{r}" for r in rels)
                    mapping["TOOLS_BIN"] = tools_bin
                    mapping["TOOL_VERSIONS"] = tool_lines

                assert_no_ground_truth(ws)

                aud_tpl = PROMPTS_DIR / aud_tpl_name.format(
                    baseline="_baseline" if is_baseline else "")
                prompt_text, aud_ver = rp.render(aud_tpl, mapping)
                (run_dir / "prompt.md").write_text(prompt_text)

                gt_path = PROJ / "evals" / ev / "findings.json"
                gt = json.loads(gt_path.read_text())
                gt_list = gt if isinstance(gt, list) else gt.get("findings", [])
                grader_text, gr_ver = rp.render(grader_tpl, {
                    "FINDINGS_JSON_PATH": str(gt_path),
                    "RESPONSE_MD_PATH": str(run_dir / "response.md"),
                    "GRADING_JSON_PATH": str(run_dir / "grading.json"),
                    "FINDING_COUNT": len(gt_list),
                    "FINDING_IDS": ", ".join(str(f.get("id")) for f in gt_list),
                })
                (run_dir / "grader_prompt.md").write_text(grader_text)

                meta = {"skill": skill, "skill_path": skill_md, "eval_id": ev,
                        "timestamp": run_ts, "is_baseline": is_baseline,
                        "model": args.model, "tooling": args.tooling,
                        "rep": rep, "experiment": args.experiment,
                        "prompt_version": aud_ver,
                        "grader_prompt_version": gr_ver,
                        "skill_sha": skill_sha_cache.get(skill, ""),
                        "contracts_sha": contracts_sha_cache[ev],
                        "created_at": datetime.now(timezone.utc).isoformat()}
                if args.tooling == "enabled":
                    meta["tools_available"] = {k: v["version"]
                                               for k, v in tool_versions.items()}
                (run_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2))

                cell = {"index": i, "skill": skill, "skillDirName": dir_name,
                        "evalId": ev, "rep": rep, "workspace": str(ws),
                        "runDir": str(run_dir),
                        "promptPath": str(run_dir / "prompt.md"),
                        "graderPromptPath": str(run_dir / "grader_prompt.md"),
                        "responsePath": str(run_dir / "response.md"),
                        "gradingPath": str(run_dir / "grading.json"),
                        "findingsPath": str(PROJ / "evals" / ev / "findings.json"),
                        "auditorBootstrap": BOOTSTRAP.format(
                            path=run_dir / "prompt.md"),
                        "graderBootstrap": BOOTSTRAP.format(
                            path=run_dir / "grader_prompt.md")}
                (cells_dir / f"cell_{i}.json").write_text(json.dumps(cell, indent=2))
                cells.append(cell)
                manifest_cells.append({"skill": skill, "eval_id": ev, "rep": rep,
                                       "run_dir": str(run_dir.relative_to(PROJ))})
                i += 1

    EXP_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"experiment": args.experiment,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "model": args.model, "tooling": args.tooling,
                "reps": args.reps, "skills": args.skills,
                "eval_set": args.eval_set if not args.evals else None,
                "evals": eval_ids,
                "cells": manifest_cells}
    # record exact template versions used
    manifest["prompt_versions"] = {
        p.name: rp.template_version(p) for p in sorted(PROMPTS_DIR.glob("*.md"))}
    manifest_path.write_text(json.dumps(manifest, indent=2))

    cfg = {"cells_dir": str(cells_dir), "n": i, "experiment": args.experiment,
           "model": args.model, "tooling": args.tooling, "ts": ts}
    cfg_path = cells_dir.parent / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, indent=2))

    print(f"prepared {i} cells "
          f"({len(args.skills)} skills x {len(eval_ids)} evals x {args.reps} reps)")
    print(f"manifest -> {manifest_path}")
    print(f"cells    -> {cells_dir}")
    print(f"cfg      -> {cfg_path}")
    print("\nSpawn each auditor with the cell's auditorBootstrap string, then "
          "each grader with graderBootstrap. Validate with:\n"
          f"  python3 scripts/validate_runs.py --experiment {args.experiment}")


if __name__ == "__main__":
    main()
