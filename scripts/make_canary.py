#!/usr/bin/env python3
"""Build a contamination-canary variant of an eval: strip ALL comments and
rename every locally-declared contract/interface/library (and matching file
names), applying the SAME renames to the copied findings.json/metadata.json so
grading stays consistent.

Rationale: the vfp_* evals come from PUBLISHED audit reports the models may
have seen in training. If a model's recall drops sharply on the canary variant
(same code, same bugs, memorization keys removed), the original score was
partly memorization, not auditing. Function/variable names are intentionally
kept — renaming them would degrade genuine readability, confounding the test;
comments + contract/project names are the strongest memorization keys.

Creates evals/<id>_cn/ with contracts/, findings.json, metadata.json,
canary_map.json. --register adds the ids to evals/canary_set.json.

Usage:
  python3 scripts/make_canary.py vfp_00005 vfp_00011 ...
  python3 scripts/make_canary.py --set core_subset --register
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
EVALS = PROJ / "evals"

DECL_RE = re.compile(r"\b(?:abstract\s+)?(?:contract|interface|library)\s+"
                     r"([A-Za-z_$][A-Za-z0-9_$]*)")
# relative imports (./Foo.sol) are project files — their stems are
# project-identifying even when the file isn't in the eval snapshot; package
# imports (@openzeppelin/...) are generic library names and must NOT be renamed
IMPORT_RE = re.compile(r"import[^;]*?[\"'](\.\.?/[^\"']+\.sol)[\"']")


def strip_comments(src: str) -> str:
    """Remove // and /* */ comments, respecting string literals. Newlines in
    block comments are kept so line numbers stay comparable."""
    out, i, n, state = [], 0, len(src), None
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"
                i += 2
                continue
            if c == "/" and nxt == "*":
                state = "block"
                i += 2
                continue
            out.append(c)
            if c == '"':
                state = "dq"
            elif c == "'":
                state = "sq"
            i += 1
        elif state == "line":
            if c == "\n":
                state = None
                out.append(c)
            i += 1
        elif state == "block":
            if c == "*" and nxt == "/":
                state = None
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
        else:  # in string
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if (state == "dq" and c == '"') or (state == "sq" and c == "'"):
                state = None
            i += 1
    # collapse runs of blank lines left by removed comment blocks
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


def build_rename_map(sources: dict) -> dict:
    names = set()
    for text in sources.values():
        names.update(DECL_RE.findall(text))
        for imp in IMPORT_RE.findall(text):
            names.add(Path(imp).stem)
    return {name: f"CanaryC{i+1}"
            for i, name in enumerate(sorted(names))}


def apply_renames(text: str, rename: dict) -> str:
    if not rename:
        return text
    pat = re.compile(r"\b(" + "|".join(re.escape(k) for k in
                                       sorted(rename, key=len, reverse=True)) + r")\b")
    return pat.sub(lambda m: rename[m.group(1)], text)


def make_canary(eval_id: str) -> str:
    src_dir = EVALS / eval_id
    if not (src_dir / "contracts").is_dir():
        sys.exit(f"{eval_id}: no contracts/ dir")
    new_id = f"{eval_id}_cn"
    dest = EVALS / new_id
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "contracts").mkdir(parents=True)

    sources = {}
    for f in sorted((src_dir / "contracts").rglob("*.sol")):
        rel = f.relative_to(src_dir / "contracts")
        sources[rel] = strip_comments(f.read_text(errors="ignore"))
    rename = build_rename_map(sources)

    for rel, text in sources.items():
        new_text = apply_renames(text, rename)
        # rename the file too if its stem is a renamed declaration
        stem = rel.stem
        new_rel = (rel.parent / f"{rename[stem]}{rel.suffix}"
                   if stem in rename else rel)
        target = dest / "contracts" / new_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_text)

    # ground truth + metadata get the SAME renames so grading stays valid
    findings_raw = (src_dir / "findings.json").read_text()
    (dest / "findings.json").write_text(apply_renames(findings_raw, rename))
    meta = {}
    mp = src_dir / "metadata.json"
    if mp.exists():
        meta = json.loads(apply_renames(mp.read_text(), rename))
    meta["canary_of"] = eval_id
    (dest / "metadata.json").write_text(json.dumps(meta, indent=2))
    (dest / "canary_map.json").write_text(json.dumps(
        {"canary_of": eval_id, "renames": rename,
         "comments_stripped": True}, indent=2))
    print(f"  {eval_id} -> {new_id}  ({len(rename)} declarations renamed, "
          f"{len(sources)} files)")
    return new_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("evals", nargs="*")
    ap.add_argument("--set", dest="eval_set",
                    help="canary every eval in evals/<set>.json")
    ap.add_argument("--register", action="store_true",
                    help="write/update evals/canary_set.json")
    args = ap.parse_args()

    ids = list(args.evals)
    if args.eval_set:
        data = json.loads((EVALS / f"{args.eval_set}.json").read_text())
        entries = data["evals"] if isinstance(data, dict) else data
        ids += [e if isinstance(e, str) else e["eval_id"] for e in entries]
    if not ids:
        ap.error("give eval ids or --set")

    new_ids = [make_canary(e) for e in ids]
    if args.register:
        reg_path = EVALS / "canary_set.json"
        existing = []
        if reg_path.exists():
            existing = json.loads(reg_path.read_text()).get("evals", [])
        merged = sorted(set(existing) | set(new_ids))
        reg_path.write_text(json.dumps({"evals": merged}, indent=2))
        print(f"registered {len(merged)} canary evals -> {reg_path}")
    print("\nRun the canary experiment with e.g.:\n"
          "  python3 scripts/prepare_run.py --experiment canary-<model> "
          "--skills baseline --eval-set canary_set --model <model> --reps 1\n"
          "then compare recall vs the same skill/model on the originals.")


if __name__ == "__main__":
    main()
