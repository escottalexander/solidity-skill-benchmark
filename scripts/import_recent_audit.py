#!/usr/bin/env python3
"""Import a recently-published audit (post model-cutoff) as a fresh eval.

Fresh evals fix the benchmark's biggest confidence gap: the vfp_* evals come
from published audit reports that may be in model training data. An eval
imported from an audit published AFTER the benchmarked models' cutoffs cannot
be memorized. Fresh evals are also full cloned projects pinned to the audited
commit, so — unlike the vfp_* partial snapshots — they COMPILE, making them
usable for the tooling A/B as well.

Input: a spec JSON (one per audit; keep them in evals/import_specs/):
{
  "eval_id": "fr_00001",
  "project_name": "...",
  "source": {"platform": "sherlock", "report_url": "...", "report_date": "2026-05-14"},
  "repo_url": "https://github.com/org/repo",
  "commit": "<full sha the contest/report pinned>",
  "framework": "foundry",
  "scope": ["src/Foo.sol", "src/vault/"],
  "findings": [
    {"id": 0, "title": "...", "severity": "High", "description": "...",
     "location": "...", "files": ["src/Foo.sol"]}
  ]
}

What it does:
  1. clones repo_url at commit (with submodules) into .cache/imports/<eval_id>/repo
  2. runs `forge build` there — the eval is rejected if it does not compile
  3. copies the scope files to evals/<eval_id>/contracts/ (repo-relative paths
     preserved) for source-only audits
  4. writes findings.json, metadata.json, project_lock.json (repo, commit,
     submodule pins, remappings, scope) — prepare_run.py uses project_lock to
     build tooling workspaces from the cached clone
  5. registers the eval in evals/evals.json and evals/fresh_set.json

Usage:
  python3 scripts/import_recent_audit.py evals/import_specs/fr_00001.json [...]
  python3 scripts/import_recent_audit.py --all       # every spec in import_specs/
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
EVALS = PROJ / "evals"
SPECS = EVALS / "import_specs"
CACHE = PROJ / ".cache" / "imports"


def sh(cmd, cwd=None, timeout=900, env=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env)


# lib-dir name (as remapped in the repo) -> shared lib cache key
# (scripts/compile_eval.py maintains the cache via --setup-cache)
_LIB_CACHE_MAP = {
    "openzeppelin-contracts": "oz-v5",
    "openzeppelin-contracts-upgradeable": "ozup-v5",
    "forge-std": "forge-std",
    "solady": "solady",
    "solmate": "solmate",
}


def ensure_lib_deps(repo):
    """Some repos gitignore lib/ (deps installed via `forge install`, never
    committed) and have no submodules, so the clone lands with empty/missing
    dependency dirs. Fill any lib/<name> that a remapping needs but is missing
    or empty by symlinking from the shared lib cache."""
    remap_file = repo / "remappings.txt"
    toml = (repo / "foundry.toml")
    text = ""
    if remap_file.exists():
        text += remap_file.read_text()
    if toml.exists():
        text += toml.read_text()
    lib_dir = repo / "lib"
    needed = set(re.findall(r"lib/([A-Za-z0-9_.-]+)", text))
    if not needed:
        return
    import compile_eval as ce
    filled = []
    for name in needed:
        target = lib_dir / name
        if target.exists() and any(target.iterdir()):
            continue
        cache_key = _LIB_CACHE_MAP.get(name)
        src = ce.LIB_CACHE / cache_key if cache_key else None
        if src and src.exists():
            if not (ce.LIB_CACHE / "oz-v5").exists():
                ce.setup_cache()
            lib_dir.mkdir(exist_ok=True)
            if target.is_symlink() or target.exists():
                target.unlink()
            target.symlink_to(os.path.realpath(src))
            filled.append(name)
    if filled:
        print(f"   filled missing lib deps from cache: {', '.join(filled)}")


def clone_at_commit(repo_url, commit, dest):
    if (dest / "foundry.toml").exists() or (dest / ".git").exists():
        head = sh(["git", "rev-parse", "HEAD"], cwd=dest).stdout.strip()
        if head == commit:
            return
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for cmd in (["git", "init", "-q"],
                ["git", "remote", "add", "origin", repo_url],
                ["git", "fetch", "-q", "--depth", "1", "origin", commit],
                ["git", "checkout", "-q", "FETCH_HEAD"]):
        r = sh(cmd, cwd=dest)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd)}: {r.stderr.strip()[:400]}")
    r = sh(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"],
           cwd=dest, timeout=1200)
    if r.returncode != 0:
        # some repos have broken optional submodules; try non-recursive
        sh(["git", "submodule", "update", "--init", "--depth", "1"], cwd=dest,
           timeout=1200)


def submodule_pins(repo):
    r = sh(["git", "submodule", "status", "--recursive"], cwd=repo)
    pins = []
    for line in r.stdout.splitlines():
        parts = line.strip().lstrip("+-U").split()
        if len(parts) >= 2:
            pins.append({"commit": parts[0], "path": parts[1]})
    return pins


def import_spec(spec_path):
    spec = json.loads(Path(spec_path).read_text())
    eval_id = spec["eval_id"]
    print(f"== {eval_id}: {spec.get('project_name', '?')}")
    repo = CACHE / eval_id / "repo"
    print(f"   cloning {spec['repo_url']} @ {spec['commit'][:12]}...")
    clone_at_commit(spec["repo_url"], spec["commit"], repo)

    if spec.get("framework", "foundry") != "foundry":
        print(f"   SKIP: framework {spec.get('framework')} not supported yet")
        return False
    if not (repo / "foundry.toml").exists():
        # some repos keep the foundry project in a subdir
        cands = list(repo.glob("*/foundry.toml"))
        if len(cands) == 1:
            repo = cands[0].parent
            print(f"   foundry project found in subdir: {repo.name}/")
        else:
            print("   FAIL: no foundry.toml found")
            return False

    ensure_lib_deps(repo)
    print("   forge build...")
    env = dict(os.environ)
    r = sh(["forge", "build"], cwd=repo, timeout=900, env=env)
    if r.returncode != 0 and "Stack too deep" in (r.stdout + r.stderr):
        print("   stack-too-deep; retrying with --via-ir + optimizer")
        env["FOUNDRY_VIA_IR"] = "true"
        env["FOUNDRY_OPTIMIZER"] = "true"
        r = sh(["forge", "build"], cwd=repo, timeout=1200, env=env)
    if r.returncode != 0:
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-12:])
        print(f"   FAIL: does not compile:\n{tail}")
        return False
    remap = sh(["forge", "remappings"], cwd=repo).stdout.strip().splitlines()

    # collect scope files
    scope_files = []
    for s in spec["scope"]:
        p = repo / s
        if p.is_dir():
            scope_files += sorted(p.rglob("*.sol"))
        elif p.is_file():
            scope_files.append(p)
        else:
            print(f"   WARN scope path missing in repo: {s}")
    if not scope_files:
        print("   FAIL: no scope files resolved")
        return False

    dest = EVALS / eval_id
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "contracts").mkdir(parents=True)
    for f in scope_files:
        rel = f.relative_to(repo)
        t = dest / "contracts" / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)

    findings = spec["findings"]
    (dest / "findings.json").write_text(json.dumps(findings, indent=2))
    sev = {}
    for f in findings:
        sev[f.get("severity", "?")] = sev.get(f.get("severity", "?"), 0) + 1
    (dest / "metadata.json").write_text(json.dumps({
        "project_name": spec.get("project_name", ""),
        "source": spec.get("source", {}),
        "repo_url": spec["repo_url"],
        "commit": spec["commit"],
        "post_cutoff": True,
        "compiles": True,
        "n_findings": len(findings),
        "severity_counts": sev,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    (dest / "project_lock.json").write_text(json.dumps({
        "repo_url": spec["repo_url"],
        "commit": spec["commit"],
        "project_subdir": str(repo.relative_to(CACHE / eval_id / "repo"))
                          if repo != CACHE / eval_id / "repo" else ".",
        "framework": "foundry",
        "remappings": remap,
        "submodules": submodule_pins(repo),
        "scope": spec["scope"],
    }, indent=2))
    print(f"   OK: {len(scope_files)} scope files, {len(findings)} findings "
          f"({', '.join(f'{k}:{v}' for k, v in sorted(sev.items()))})")
    return True


def register(eval_ids):
    # evals.json registry
    reg_path = EVALS / "evals.json"
    reg = json.loads(reg_path.read_text()) if reg_path.exists() else {"evals": []}
    known = {e if isinstance(e, str) else e.get("eval_id") for e in reg["evals"]}
    for e in eval_ids:
        if e not in known:
            reg["evals"].append({"eval_id": e})
    reg_path.write_text(json.dumps(reg, indent=2))
    # fresh_set.json
    fs_path = EVALS / "fresh_set.json"
    fs = json.loads(fs_path.read_text()) if fs_path.exists() else {"evals": []}
    fs["evals"] = sorted(set(fs["evals"]) | set(eval_ids))
    fs_path.write_text(json.dumps(fs, indent=2))
    print(f"registered {len(eval_ids)} evals in evals.json + fresh_set.json "
          f"({len(fs['evals'])} fresh evals total)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs", nargs="*")
    ap.add_argument("--all", action="store_true",
                    help="import every spec in evals/import_specs/")
    args = ap.parse_args()
    paths = ([str(p) for p in sorted(SPECS.glob("*.json"))] if args.all
             else args.specs)
    if not paths:
        ap.error("give spec files or --all")
    ok = []
    for p in paths:
        try:
            if import_spec(p):
                ok.append(json.loads(Path(p).read_text())["eval_id"])
        except Exception as e:
            print(f"   FAIL {p}: {e}")
    if ok:
        register(ok)
    print(f"\n{len(ok)}/{len(paths)} imported")
    sys.exit(0 if len(ok) == len(paths) else 1)


if __name__ == "__main__":
    main()
