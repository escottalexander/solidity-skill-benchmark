#!/usr/bin/env python3
"""Grader calibration against human labels — measures the measurement
instrument. Until grader accuracy on a hand-labeled set is known, leaderboard
gaps smaller than the grader's own error rate are meaningless.

Workflow:
  1. --sample N: deterministically sample N (run, ground-truth finding) pairs,
     stratified across skills and verdicts, and write
     results/calibration/labels_todo.json. Each entry shows the ground-truth
     finding and the grader's verdict + evidence, plus the response path.
  2. A HUMAN fills in "human_found" (true/false) for each entry — read the
     response yourself; do not look at the grader verdict first (it's placed
     last in each entry for that reason). Save as results/calibration/labels.json.
  3. --report: grader accuracy / precision / recall / kappa vs the human
     labels, plus the list of disagreements to review.

Usage:
  python3 scripts/grader_calibration.py --sample 80 [--experiment NAME]
  python3 scripts/grader_calibration.py --report
"""
import argparse
import json
import random
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
RUNS = PROJ / "results" / "runs"
EXP_DIR = PROJ / "results" / "experiments"
CAL_DIR = PROJ / "results" / "calibration"
SEED = 42


def graded_runs(experiment=None):
    if experiment:
        manifest = json.loads((EXP_DIR / f"{experiment}.json").read_text())
        for c in manifest["cells"]:
            d = PROJ / c["run_dir"]
            if (d / "grading.json").exists() and (d / "response.md").exists():
                yield d, c["eval_id"]
        return
    for skill_dir in sorted(RUNS.iterdir()):
        if not skill_dir.is_dir():
            continue
        for eval_dir in sorted(skill_dir.iterdir()):
            if not eval_dir.is_dir():
                continue
            for d in sorted(eval_dir.iterdir()):
                if (d / "grading.json").exists() and (d / "response.md").exists():
                    yield d, eval_dir.name


def sample(args):
    pool = []  # (run_dir, eval_id, gt_finding, grader_verdict)
    for run_dir, eval_id in graded_runs(args.experiment):
        try:
            g = json.loads((run_dir / "grading.json").read_text())
            gt = json.loads((PROJ / "evals" / eval_id / "findings.json").read_text())
        except Exception:
            continue
        gt_list = gt if isinstance(gt, list) else gt.get("findings", [])
        gt_by_id = {f.get("id"): f for f in gt_list}
        for f in g.get("findings", []):
            if f.get("id") in gt_by_id:
                pool.append((run_dir, eval_id, gt_by_id[f["id"]], f))
    rng = random.Random(SEED)
    rng.shuffle(pool)
    # stratify: half grader-found, half grader-missed (found verdicts are rarer
    # and errors there hurt more)
    found = [p for p in pool if p[3].get("found")]
    missed = [p for p in pool if not p[3].get("found")]
    n_half = args.sample // 2
    chosen = found[:n_half] + missed[:args.sample - min(n_half, len(found))]
    chosen = chosen[:args.sample]
    entries = []
    for run_dir, eval_id, gt_f, gr_f in chosen:
        entries.append({
            "run_dir": str(run_dir.relative_to(PROJ)),
            "eval_id": eval_id,
            "finding_id": gt_f.get("id"),
            "finding_title": gt_f.get("title", ""),
            "finding_severity": gt_f.get("severity", ""),
            "finding_description": (gt_f.get("description") or "")[:1200],
            "response_path": str((run_dir / "response.md").relative_to(PROJ)),
            "human_found": None,          # <- FILL THIS IN (true/false)
            "human_note": "",
            "grader_found": bool(gr_f.get("found")),
            "grader_evidence": gr_f.get("evidence", ""),
        })
    CAL_DIR.mkdir(parents=True, exist_ok=True)
    out = CAL_DIR / "labels_todo.json"
    out.write_text(json.dumps(entries, indent=2))
    print(f"wrote {len(entries)} pairs -> {out}")
    print("Label each entry's human_found by reading the response yourself "
          "(ignore grader_found until after), then save as "
          f"{CAL_DIR / 'labels.json'} and run --report.")


def report(_args):
    path = CAL_DIR / "labels.json"
    if not path.exists():
        sys.exit(f"{path} not found — fill in labels_todo.json and save it there")
    entries = json.loads(path.read_text())
    labeled = [e for e in entries if e.get("human_found") is not None]
    if not labeled:
        sys.exit("no entries have human_found filled in")
    tp = sum(1 for e in labeled if e["grader_found"] and e["human_found"])
    tn = sum(1 for e in labeled if not e["grader_found"] and not e["human_found"])
    fp = sum(1 for e in labeled if e["grader_found"] and not e["human_found"])
    fn = sum(1 for e in labeled if not e["grader_found"] and e["human_found"])
    n = len(labeled)
    acc = (tp + tn) / n
    p_yes_g = (tp + fp) / n
    p_yes_h = (tp + fn) / n
    pe = p_yes_g * p_yes_h + (1 - p_yes_g) * (1 - p_yes_h)
    kappa = (acc - pe) / (1 - pe) if pe < 1 else 1.0
    print(f"labeled pairs      : {n} (of {len(entries)})")
    print(f"grader accuracy    : {acc:.1%}")
    print(f"confusion          : TP={tp} TN={tn} FP={fp} FN={fn}")
    if tp + fp:
        print(f"grader 'found' precision : {tp/(tp+fp):.1%}  "
              f"(when grader credits a find, human agrees this often)")
    if tp + fn:
        print(f"grader 'found' recall    : {tp/(tp+fn):.1%}  "
              f"(of human-confirmed finds, grader credits this many)")
    print(f"Cohen's kappa      : {kappa:.3f}")
    dis = [e for e in labeled if e["grader_found"] != e["human_found"]]
    if dis:
        print(f"\ndisagreements ({len(dis)}):")
        for e in dis:
            print(f"  - {e['run_dir']} finding {e['finding_id']} "
                  f"({e['finding_title'][:60]}): grader={e['grader_found']} "
                  f"human={e['human_found']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--experiment")
    args = ap.parse_args()
    if bool(args.sample) == args.report:
        ap.error("pass exactly one of --sample N / --report")
    (report if args.report else sample)(args)


if __name__ == "__main__":
    main()
