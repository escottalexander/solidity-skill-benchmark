#!/usr/bin/env python3
"""Build harness: turn an eval's partial contract snapshot into a compiling
Foundry project so static-analysis tools can run on it.

Strategy: scaffold a Foundry project around evals/<id>/contracts (structure
preserved so relative imports resolve), symlink the needed dependency libs from
a shared cache, write remappings, let Foundry auto-pick solc from the pragma,
and run `forge build`. OpenZeppelin major version is detected from import paths
(v4 vs v5); on build failure with the guessed version we retry the other.

Usage:
  python3 scripts/compile_eval.py <eval_id> [--dest DIR] [--keep]
  python3 scripts/compile_eval.py --setup-cache   # pre-clone the lib cache
Exit code 0 = compiled, 1 = did not compile.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SCRATCH = Path(os.environ.get("TOOLING_SCRATCH",
              "/private/tmp/claude-501/-Users-elliott-dev-solidity-skill-benchmark/02e0cd49-0bf6-4ff7-afe2-8ca964942215/scratchpad"))
LIB_CACHE = SCRATCH / "lib_cache"

# dep name -> (git url, {version_key: tag})
DEP_REPOS = {
    "oz-v5":     ("https://github.com/OpenZeppelin/openzeppelin-contracts", "v5.0.2"),
    "oz-v4":     ("https://github.com/OpenZeppelin/openzeppelin-contracts", "v4.9.6"),
    "ozup-v5":   ("https://github.com/OpenZeppelin/openzeppelin-contracts-upgradeable", "v5.0.2"),
    "ozup-v4":   ("https://github.com/OpenZeppelin/openzeppelin-contracts-upgradeable", "v4.9.6"),
    "solady":    ("https://github.com/Vectorized/solady", "v0.0.228"),
    "solmate":   ("https://github.com/transmissions11/solmate", "v7"),
    "v3-core":   ("https://github.com/Uniswap/v3-core", "v1.0.0"),
    "forge-std": ("https://github.com/foundry-rs/forge-std", "v1.9.4"),
}


def sh(cmd, cwd=None, timeout=300):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


def setup_cache():
    LIB_CACHE.mkdir(parents=True, exist_ok=True)
    for name, (url, tag) in DEP_REPOS.items():
        dest = LIB_CACHE / name
        if dest.exists():
            continue
        print(f"  cloning {name} ({tag})...")
        r = sh(["git", "clone", "--depth", "1", "--branch", tag, url, str(dest)],
               timeout=600)
        if r.returncode != 0:
            print(f"    WARN failed to clone {name}: {r.stderr.strip()[:200]}")
    print("lib cache ready at", LIB_CACHE)


def eval_imports(eval_id):
    base = PROJ / "evals" / eval_id / "contracts"
    imps = []
    for f in base.rglob("*.sol"):
        for imp in re.findall(r'import[^;\"\']*[\"\']([^\"\']+)[\"\']',
                              f.read_text(errors="ignore")):
            imps.append(imp)
    return imps


def detect_oz_version(imports):
    """v4 vs v5 from import-path markers. Returns 'v5' or 'v4' (best guess)."""
    joined = "\n".join(imports)
    v5_markers = ["utils/Panic.sol", "utils/Nonces.sol", "interfaces/draft-IERC6093",
                  "/governance/utils/Votes"]
    v4_markers = ["/security/ReentrancyGuard", "/security/Pausable",
                  "draft-ERC20Permit", "/utils/Counters.sol"]
    if any(m in joined for m in v5_markers) and not any(m in joined for m in v4_markers):
        return "v5"
    if any(m in joined for m in v4_markers):
        return "v4"
    return "v5"  # default to latest


def needed_libs(imports, oz_ver):
    libs = {}  # cache_name -> remapping_prefix info handled below
    j = "\n".join(imports)
    if "@openzeppelin/contracts-upgradeable/" in j:
        libs["ozup-" + oz_ver] = True
        libs["oz-" + oz_ver] = True  # upgradeable depends on contracts
    if "@openzeppelin/contracts/" in j:
        libs["oz-" + oz_ver] = True
    if "solady/" in j or "@solady/" in j:
        libs["solady"] = True
    if re.search(r'\bsolmate/', j):
        libs["solmate"] = True
    if "@uniswap/v3-core/" in j:
        libs["v3-core"] = True
    libs["forge-std"] = True
    return list(libs.keys())


def remappings_for(libs, oz_ver):
    rm = []
    for name in libs:
        if name == f"oz-{oz_ver}":
            rm.append(f"@openzeppelin/contracts/=lib/oz-{oz_ver}/contracts/")
        elif name == f"ozup-{oz_ver}":
            rm.append(f"@openzeppelin/contracts-upgradeable/=lib/ozup-{oz_ver}/contracts/")
        elif name == "solady":
            rm.append("solady/=lib/solady/src/")
            rm.append("@solady/=lib/solady/src/")
        elif name == "solmate":
            rm.append("solmate/=lib/solmate/src/")
        elif name == "v3-core":
            rm.append("@uniswap/v3-core/=lib/v3-core/")
        elif name == "forge-std":
            rm.append("forge-std/=lib/forge-std/src/")
    return rm


def attempt_build(eval_id, dest, oz_ver):
    base = PROJ / "evals" / eval_id / "contracts"
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "src").mkdir(parents=True)
    (dest / "lib").mkdir()
    # copy contracts preserving structure so relative imports resolve
    for f in base.rglob("*.sol"):
        rel = f.relative_to(base)
        target = dest / "src" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    imports = eval_imports(eval_id)
    libs = needed_libs(imports, oz_ver)
    for name in libs:
        src = LIB_CACHE / name
        if src.exists():
            os.symlink(src, dest / "lib" / name)
    rm = remappings_for(libs, oz_ver)
    (dest / "remappings.txt").write_text("\n".join(rm) + "\n")
    (dest / "foundry.toml").write_text(
        "[profile.default]\nsrc = \"src\"\nlibs = [\"lib\"]\n"
        "auto_detect_solc = true\noptimizer = false\n")
    r = sh(["forge", "build"], cwd=str(dest), timeout=420)
    ok = r.returncode == 0
    out = (r.stdout + r.stderr)
    err_tail = "\n".join(l for l in out.splitlines()
                         if "Error" in l or "error" in l)[-1500:]
    return ok, oz_ver, libs, err_tail


def build_eval(eval_id, dest):
    """Try the guessed OZ version, fall back to the other. Returns status dict."""
    imports = eval_imports(eval_id)
    first = detect_oz_version(imports)
    order = [first, "v4" if first == "v5" else "v5"]
    last = None
    for ver in order:
        ok, used, libs, err = attempt_build(eval_id, dest, ver)
        last = {"eval_id": eval_id, "compiled": ok, "oz_version": used,
                "libs": libs, "error_tail": "" if ok else err}
        if ok:
            return last
        # only retry the other OZ version if OZ is actually used
        if not any(l.startswith("oz") for l in libs):
            break
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_id", nargs="?")
    ap.add_argument("--dest")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--setup-cache", action="store_true")
    args = ap.parse_args()
    if args.setup_cache:
        setup_cache()
        return
    if not args.eval_id:
        ap.error("eval_id required (or --setup-cache)")
    if not (LIB_CACHE / "oz-v5").exists():
        print("lib cache missing; run --setup-cache first", file=sys.stderr)
        sys.exit(2)
    dest = args.dest or tempfile.mkdtemp(prefix=f"build_{args.eval_id}_")
    status = build_eval(args.eval_id, dest)
    print(json.dumps(status, indent=2))
    if not args.keep and not args.dest:
        shutil.rmtree(dest, ignore_errors=True)
    sys.exit(0 if status["compiled"] else 1)


if __name__ == "__main__":
    main()
