#!/usr/bin/env python3
"""Find which evals can be compiled, to form the tooling A/B comparison set.

Recomputes the compile-candidate heuristic (no missing local files + only
installable deps) across all evals, then actually builds each candidate via
compile_eval.build_eval. Writes evals/tooling_set.json with the evals that
truly compiled.

Usage: python3 scripts/discover_compilable.py [--candidates id,id,...]
"""
import json
import os
import re
import glob
import tempfile
import shutil
from pathlib import Path

import compile_eval as ce

PROJ = Path(__file__).resolve().parent.parent
INSTALLABLE = ("@openzeppelin/contracts", "@openzeppelin/contracts-upgradeable",
               "solady", "@solady", "forge-std", "solmate", "@uniswap/v3-core")


def candidates():
    out = []
    for ev in sorted(d.name for d in (PROJ / "evals").iterdir()
                     if d.name.startswith("vfp_")):
        base = PROJ / "evals" / ev / "contracts"
        files = list(base.rglob("*.sol"))
        if not files:
            continue
        present = {os.path.normpath(str(f.relative_to(base))) for f in files}
        missing_local = 0
        ext = set()
        for f in files:
            d = os.path.dirname(str(f.relative_to(base)))
            for imp in re.findall(r'import[^;\"\']*[\"\']([^\"\']+)[\"\']',
                                  f.read_text(errors="ignore")):
                if imp.startswith("."):
                    if os.path.normpath(os.path.join(d, imp)) not in present:
                        missing_local += 1
                elif imp.startswith("@"):
                    ext.add("/".join(imp.split("/")[:2]))
                else:
                    if os.path.normpath(imp) not in present:
                        ext.add(imp.split("/")[0])
        unins = [e for e in ext if not any(e.startswith(p) for p in INSTALLABLE)]
        if missing_local == 0 and not unins:
            out.append(ev)
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", help="comma-separated eval ids (override)")
    args = ap.parse_args()

    if not (ce.LIB_CACHE / "oz-v5").exists():
        print("Setting up lib cache first...")
        ce.setup_cache()

    cands = args.candidates.split(",") if args.candidates else candidates()
    print(f"{len(cands)} compile-candidates to attempt:\n  {cands}\n")

    results = []
    compiled = []
    for i, ev in enumerate(cands, 1):
        dest = tempfile.mkdtemp(prefix=f"disc_{ev}_")
        try:
            st = ce.build_eval(ev, dest)
        except Exception as e:
            st = {"eval_id": ev, "compiled": False, "error_tail": f"harness error: {e}"}
        finally:
            shutil.rmtree(dest, ignore_errors=True)
        results.append(st)
        mark = "OK " if st["compiled"] else "FAIL"
        if st["compiled"]:
            compiled.append(ev)
        print(f"  [{i:2}/{len(cands)}] {mark} {ev}  (oz={st.get('oz_version','-')})"
              + ("" if st["compiled"] else f"  :: {st.get('error_tail','')[:90]}"))

    # write build_status per eval + the tooling_set
    for st in results:
        p = PROJ / "evals" / st["eval_id"] / "build_status.json"
        p.write_text(json.dumps(st, indent=2))

    out = {
        "description": "Evals that compile, used for the tooling-enabled vs disabled A/B.",
        "compiled_count": len(compiled),
        "attempted": len(cands),
        "evals": compiled,
    }
    (PROJ / "evals" / "tooling_set.json").write_text(json.dumps(out, indent=2))
    print(f"\nCompiled {len(compiled)}/{len(cands)}. Wrote evals/tooling_set.json")
    print(f"GATE: {'PASS (>=12)' if len(compiled) >= 12 else 'BELOW 12 - reconsider'}")


if __name__ == "__main__":
    main()
