#!/usr/bin/env python3
"""Backfill per-run auditor token totals into run_metadata.json (and the
run_metadata copy embedded in grading.json) from workflow agent transcripts.

Workflow-orchestrated experiment runs often never record tokens (the
orchestrator doesn't reliably see subagent usage), so this reconstructs them
the same way scripts/token_usage.py does: scan every agent transcript, find
the agent that wrote each run's response.md, and sum its usage across turns
(input + output + cache_read + cache_creation). When several transcripts
wrote the same response.md (re-run cells), only the LATEST writer counts —
its Write is the report that was actually graded (verified against disk), so
its tokens are the cost of the graded audit; earlier discarded attempts are
harness retry waste, not skill cost.

Existing non-zero tokens in run_metadata.json are left alone unless
--overwrite is given. Writes are atomic (tmp + rename) so an interrupted run
can never corrupt a grading.json.

Usage:
  python3 scripts/backfill_tokens.py --experiment full-sonnet5-a [--experiment ...]
      [--transcripts <dir> ...] [--dry-run] [--overwrite]

Default transcript location: every */subagents and */subagents/workflows/wf_*
directory under the Claude projects dir for this repository
(~/.claude*/projects/<flattened-repo-path>/).
"""
import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
EXP_DIR = PROJ_ROOT / "results" / "experiments"


def default_transcript_dirs():
    flat = str(PROJ_ROOT).replace("/", "-")
    dirs = []
    for base in sorted(Path.home().glob(".claude*")):
        proj = base / "projects" / flat
        if not proj.is_dir():
            continue
        dirs.extend(glob.glob(str(proj / "*" / "subagents")))
        dirs.extend(glob.glob(str(proj / "*" / "subagents" / "workflows" / "wf_*")))
    return dirs


def scan_transcript(path):
    """Return (response_md_path, total_tokens) if this agent wrote a
    response.md, else (None, 0)."""
    rp = None
    tot = 0
    for ln in open(path, errors="ignore"):
        if '"usage"' not in ln and "response.md" not in ln:
            continue
        try:
            e = json.loads(ln)
        except Exception:
            continue
        msg = e.get("message", {})
        u = msg.get("usage")
        if u:
            tot += (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0) + u.get("output_tokens", 0))
        content = msg.get("content")
        for c in (content if isinstance(content, list) else []):
            if (c.get("type") == "tool_use" and c.get("name") == "Write"
                    and str(c.get("input", {}).get("file_path", "")).endswith("response.md")):
                rp = c["input"]["file_path"]
    return rp, tot


def build_token_map(tdirs):
    """response.md abspath -> auditor tokens of the transcript that wrote it
    last (the attempt whose report was graded)."""
    latest = {}  # path -> (mtime, tokens)
    n_files = 0
    for d in tdirs:
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            n_files += 1
            rp, tot = scan_transcript(f)
            if rp and "/runs/" in rp and tot:
                key = os.path.normpath(rp)
                mt = os.path.getmtime(f)
                if key not in latest or mt > latest[key][0]:
                    latest[key] = (mt, tot)
    by_path = {k: tok for k, (mt, tok) in latest.items()}
    print(f"Scanned {n_files} transcripts in {len(tdirs)} dirs; "
          f"{len(by_path)} auditor transcripts mapped to run dirs")
    return by_path


def atomic_write(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n")
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", action="append", required=True,
                    help="experiment manifest name (repeatable)")
    ap.add_argument("--transcripts", nargs="*", default=None,
                    help="transcript dirs to scan (default: auto-discover)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace existing non-zero token totals too")
    args = ap.parse_args()

    tdirs = args.transcripts or default_transcript_dirs()
    if not tdirs:
        sys.exit("no transcript dirs found; pass --transcripts explicitly")
    by_path = build_token_map(tdirs)

    stats = defaultdict(lambda: [0, 0, 0])  # experiment -> [cells, backfilled, missing]
    for name in args.experiment:
        manifest = json.loads((EXP_DIR / f"{name}.json").read_text())
        for c in manifest["cells"]:
            run_dir = PROJ_ROOT / c["run_dir"]
            stats[name][0] += 1
            rp = os.path.normpath(str(run_dir / "response.md"))
            tot = by_path.get(rp)
            if not tot:
                stats[name][2] += 1
                continue

            mp = run_dir / "run_metadata.json"
            meta = json.loads(mp.read_text()) if mp.exists() else {}
            existing = (meta.get("tokens") or {}).get("total")
            if existing and not args.overwrite:
                continue
            stats[name][1] += 1
            if args.dry_run:
                continue
            meta["tokens"] = {"total": tot}
            atomic_write(mp, meta)

            gp = run_dir / "grading.json"
            if gp.exists():
                try:
                    grading = json.loads(gp.read_text())
                except Exception:
                    continue  # never touch an unparseable grading.json
                rm = grading.get("run_metadata") or {}
                rm["tokens"] = {"total": tot}
                grading["run_metadata"] = rm
                atomic_write(gp, grading)

    print(f"\n{'experiment':<24}{'cells':>7}{'backfilled':>12}{'no transcript':>15}")
    for name, (cells, done, miss) in stats.items():
        print(f"{name:<24}{cells:>7}{done:>12}{miss:>15}")
    if args.dry_run:
        print("(dry run — nothing written)")


if __name__ == "__main__":
    main()
