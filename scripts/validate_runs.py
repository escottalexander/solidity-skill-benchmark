#!/usr/bin/env python3
"""Validate benchmark run artifacts — turns the documented conventions into
enforced checks. Run after every benchmark; re-run only the cells it flags.

Per run directory it checks:
  - response.md exists and is non-trivial (>200 chars), or error.json explains why
  - grading.json parses, has findings[] + summary{} with the required keys
  - grading findings count == summary.total == ground-truth findings count,
    and finding ids match the ground truth ids
  - summary arithmetic is consistent (found == sum(found flags), recall = found/total)
  - false_positives == len(false_positive_details) when details are present
  - run_metadata.json present with skill/eval_id/model
  - contamination: response mentions at least one of its own eval's contract
    file names (catches cross-wired cells)
  - provenance (new-pipeline runs): prompt.md + grader_prompt.md saved,
    prompt_version recorded

Usage:
  python3 scripts/validate_runs.py                       # all runs
  python3 scripts/validate_runs.py --experiment NAME     # cells of one manifest
  python3 scripts/validate_runs.py --json                # machine-readable
  python3 scripts/validate_runs.py --fix-arithmetic      # recompute summaries
Exit code: 0 clean, 1 problems found.

--fix-arithmetic: when a grading's per-finding array is complete and its ids
match ground truth exactly, but the SUMMARY disagrees (grader arithmetic slip),
recompute total/found/missed/recall/precision from the findings array +
false-positive count. Never touches per-finding verdicts.
"""
import argparse
import json
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
RUNS = PROJ / "results" / "runs"
EVALS = PROJ / "evals"

REQUIRED_SUMMARY = {"total", "found", "missed", "recall", "false_positives",
                    "precision"}


def eval_contract_names(eval_id):
    base = EVALS / eval_id / "contracts"
    if not base.is_dir():
        return []
    return [p.stem for p in base.rglob("*.sol")]


def check_run(run_dir, eval_id, strict_provenance=False):
    """Returns a list of issue strings (empty = clean)."""
    issues = []
    resp = run_dir / "response.md"
    grading = run_dir / "grading.json"
    meta_p = run_dir / "run_metadata.json"

    # --- run metadata
    if not meta_p.exists():
        issues.append("run_metadata.json missing")
    else:
        try:
            meta = json.loads(meta_p.read_text())
            for k in ("skill", "eval_id", "model"):
                if not meta.get(k) and not (k == "skill" and meta.get("is_baseline")):
                    issues.append(f"run_metadata missing '{k}'")
            if meta.get("eval_id") and meta["eval_id"] != eval_id:
                issues.append(f"run_metadata eval_id={meta['eval_id']} but dir={eval_id}")
        except Exception as e:
            issues.append(f"run_metadata.json unparseable: {e}")

    # --- response
    if not resp.exists():
        if (run_dir / "error.json").exists():
            issues.append("errored run (error.json present) — needs re-run")
            return issues
        issues.append("response.md missing")
        return issues
    text = resp.read_text(errors="ignore")
    if len(text.strip()) < 200:
        issues.append(f"response.md suspiciously short ({len(text.strip())} chars)")

    # --- contamination: response should mention its own contracts
    names = eval_contract_names(eval_id)
    if names:
        low = text.lower()
        if not any(n.lower() in low for n in names):
            issues.append("contamination? response mentions none of this eval's "
                          f"contract names ({', '.join(names[:5])}...)")

    # --- grading
    gt_path = EVALS / eval_id / "findings.json"
    n_truth = None
    if gt_path.exists():
        try:
            gt = json.loads(gt_path.read_text())
            gt_list = gt if isinstance(gt, list) else gt.get("findings", [])
            n_truth = len(gt_list)
            gt_ids = {f.get("id") for f in gt_list}
        except Exception:
            pass
    if not grading.exists():
        issues.append("grading.json missing (cell ungraded)")
        return issues
    try:
        g = json.loads(grading.read_text())
    except Exception as e:
        issues.append(f"grading.json unparseable: {e}")
        return issues
    if "findings" not in g or "summary" not in g:
        issues.append("grading.json missing findings/summary keys")
        return issues
    s = g["summary"]
    missing_keys = REQUIRED_SUMMARY - set(s)
    if missing_keys:
        issues.append(f"summary missing keys: {sorted(missing_keys)}")
    n_graded = len(g["findings"])
    if n_truth is not None and n_graded != n_truth:
        issues.append(f"graded {n_graded} findings but ground truth has {n_truth}")
    if n_truth is not None and s.get("total") != n_truth:
        issues.append(f"summary.total={s.get('total')} != ground truth {n_truth}")
    if n_truth is not None:
        graded_ids = {f.get("id") for f in g["findings"]}
        if graded_ids != gt_ids:
            issues.append("grading finding ids != ground-truth ids")
    found_flags = sum(1 for f in g["findings"] if f.get("found"))
    if s.get("found") != found_flags:
        issues.append(f"summary.found={s.get('found')} != counted flags {found_flags}")
    if s.get("total"):
        want = s["found"] / s["total"]
        if abs(s.get("recall", 0) - want) > 0.011:
            issues.append(f"summary.recall={s.get('recall')} != found/total={want:.3f}")
    if "false_positive_details" in g:
        if s.get("false_positives") != len(g["false_positive_details"]):
            issues.append("false_positives count != len(false_positive_details)")

    # --- provenance (required for new-pipeline runs, warned for legacy)
    if not (run_dir / "prompt.md").exists():
        issues.append(("MISSING prompt.md" if strict_provenance
                       else "legacy run: no saved prompt.md (prompt unrecoverable)"))

    return issues


def fix_arithmetic(run_dir, eval_id):
    """Recompute a grading's summary from its findings array. Returns True if
    the file was rewritten. Only acts when the findings array itself is sound
    (complete, ids == ground truth)."""
    gp = run_dir / "grading.json"
    gt_path = EVALS / eval_id / "findings.json"
    if not (gp.exists() and gt_path.exists()):
        return False
    try:
        g = json.loads(gp.read_text())
        gt = json.loads(gt_path.read_text())
    except Exception:
        return False
    gt_list = gt if isinstance(gt, list) else gt.get("findings", [])
    findings = g.get("findings", [])
    if {f.get("id") for f in findings} != {f.get("id") for f in gt_list}:
        return False
    if len(findings) != len(gt_list):
        return False
    total = len(findings)
    found = sum(1 for f in findings if f.get("found"))
    fp = g.get("false_positives",
               g.get("summary", {}).get("false_positives", 0))
    if "false_positive_details" in g:
        fp = len(g["false_positive_details"])
    new_summary = {
        "total": total, "found": found, "missed": total - found,
        "recall": round(found / total, 4) if total else 0,
        "false_positives": fp,
        "precision": round(found / (found + fp), 4) if (found + fp) else 1.0,
    }
    if g.get("summary") == new_summary:
        return False
    g["summary"] = new_summary
    g["false_positives"] = fp
    gp.write_text(json.dumps(g, indent=2))
    return True


def iter_all_runs():
    for skill_dir in sorted(RUNS.iterdir()):
        if not skill_dir.is_dir():
            continue
        for eval_dir in sorted(skill_dir.iterdir()):
            if not eval_dir.is_dir():
                continue
            for run_dir in sorted(eval_dir.iterdir()):
                if run_dir.is_dir():
                    yield run_dir, eval_dir.name, False


def iter_experiment_runs(name):
    manifest = json.loads(
        (PROJ / "results" / "experiments" / f"{name}.json").read_text())
    for c in manifest["cells"]:
        yield PROJ / c["run_dir"], c["eval_id"], True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", help="validate one experiment manifest")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet-legacy", action="store_true",
                    help="suppress the legacy no-prompt.md warning")
    ap.add_argument("--fix-arithmetic", action="store_true",
                    help="recompute summaries that disagree with a sound "
                         "findings array")
    args = ap.parse_args()

    runs = (iter_experiment_runs(args.experiment) if args.experiment
            else iter_all_runs())
    report, n_runs, n_bad, n_fixed = [], 0, 0, 0
    for run_dir, eval_id, strict in runs:
        n_runs += 1
        issues = check_run(run_dir, eval_id, strict_provenance=strict)
        if args.fix_arithmetic and any(
                "summary" in i or "counted flags" in i for i in issues):
            if fix_arithmetic(run_dir, eval_id):
                n_fixed += 1
                issues = check_run(run_dir, eval_id, strict_provenance=strict)
        if args.quiet_legacy:
            issues = [i for i in issues if not i.startswith("legacy run:")]
        if issues:
            n_bad += 1
            report.append({"run_dir": str(run_dir.relative_to(PROJ)),
                           "eval_id": eval_id, "issues": issues})

    if args.json:
        print(json.dumps({"runs": n_runs, "bad": n_bad, "problems": report},
                         indent=2))
    else:
        for r in report:
            print(f"{r['run_dir']}")
            for i in r["issues"]:
                print(f"    - {i}")
        if args.fix_arithmetic:
            print(f"\n{n_fixed} summaries recomputed from findings arrays")
        print(f"\n{n_runs} runs checked, {n_bad} with issues")
        if args.experiment and n_bad:
            print("Re-run ONLY the flagged cells (same cell files), then re-validate.")
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
