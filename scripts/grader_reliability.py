#!/usr/bin/env python3
"""Measure grader repeatability: grade the same responses multiple times and
quantify agreement. Grading noise is part of the benchmark's error bars — until
it's measured, small leaderboard gaps can't be trusted.

Workflow:
  1. --prepare: pick a deterministic sample of graded runs and render regrade
     prompts (regrades/<k>/grader_prompt.md targeting regrades/<k>/grading.json,
     from the SAME frozen grader template). The orchestrator then spawns one
     grader subagent per emitted cell file (use the "graderBootstrap" string).
  2. --report: compare the original grading.json with all regrades and report
     per-finding percent agreement, pooled Cohen's kappa, and FP-count spread.

Usage:
  python3 scripts/grader_reliability.py --prepare --sample 20 --k 3 [--experiment NAME]
  python3 scripts/grader_reliability.py --report [--experiment NAME]
"""
import argparse
import json
import random
import sys
from itertools import combinations
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import render_prompt as rp  # noqa: E402

PROJ = SCRIPTS.parent
RUNS = PROJ / "results" / "runs"
EXP_DIR = PROJ / "results" / "experiments"
GRADER_TPL = PROJ / "agents" / "prompts" / "grader.md"
CACHE = PROJ / ".cache" / "regrades"
SEED = 42

BOOTSTRAP = ("Read the file {path} with the Read tool, then follow its "
             "instructions exactly. That file is your complete task "
             "specification; do not deviate from it, and do not read any other "
             "file outside the locations it names.")


def graded_runs(experiment=None):
    """Yield (run_dir, eval_id) for every run with response.md + grading.json."""
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


def prepare(args):
    runs = list(graded_runs(args.experiment))
    rng = random.Random(SEED)
    sample = rng.sample(runs, min(args.sample, len(runs)))
    tag = args.experiment or "headline"
    cells_dir = CACHE / tag
    cells_dir.mkdir(parents=True, exist_ok=True)
    i = 0
    for run_dir, eval_id in sample:
        for k in range(2, args.k + 1):   # pass 1 = the original grading.json
            rd = run_dir / "regrades" / str(k)
            rd.mkdir(parents=True, exist_ok=True)
            gt_path = PROJ / "evals" / eval_id / "findings.json"
            gt = json.loads(gt_path.read_text())
            gt_list = gt if isinstance(gt, list) else gt.get("findings", [])
            text, ver = rp.render(GRADER_TPL, {
                "FINDINGS_JSON_PATH": str(gt_path),
                "RESPONSE_MD_PATH": str(run_dir / "response.md"),
                "GRADING_JSON_PATH": str(rd / "grading.json"),
                "FINDING_COUNT": len(gt_list),
                "FINDING_IDS": ", ".join(str(f.get("id")) for f in gt_list),
            })
            (rd / "grader_prompt.md").write_text(text)
            cell = {"runDir": str(run_dir), "evalId": eval_id, "pass": k,
                    "graderPromptPath": str(rd / "grader_prompt.md"),
                    "gradingPath": str(rd / "grading.json"),
                    "graderPromptVersion": ver,
                    "graderBootstrap": BOOTSTRAP.format(path=rd / "grader_prompt.md")}
            (cells_dir / f"cell_{i}.json").write_text(json.dumps(cell, indent=2))
            i += 1
    print(f"prepared {i} regrade cells for {len(sample)} runs -> {cells_dir}")
    print("Spawn one grader subagent per cell (graderBootstrap), same model as "
          "the original grading, then run --report.")


def load_passes(run_dir):
    """[{id: found}] for the original grading + each completed regrade."""
    passes = []
    try:
        g = json.loads((run_dir / "grading.json").read_text())
        passes.append(({f["id"]: bool(f["found"]) for f in g["findings"]},
                       g["summary"].get("false_positives", 0)))
    except Exception:
        return []
    rrd = run_dir / "regrades"
    if rrd.is_dir():
        for sub in sorted(rrd.iterdir()):
            gp = sub / "grading.json"
            if gp.exists():
                try:
                    g = json.loads(gp.read_text())
                    passes.append(({f["id"]: bool(f["found"]) for f in g["findings"]},
                                   g["summary"].get("false_positives", 0)))
                except Exception:
                    pass
    return passes


def report(args):
    n_runs = 0
    agree = disagree = 0
    both_yes = both_no = yes_no = 0
    unanimous_findings = total_findings = 0
    fp_spreads = []
    for run_dir, _eval in graded_runs(args.experiment):
        passes = load_passes(run_dir)
        if len(passes) < 2:
            continue
        n_runs += 1
        fmaps = [p[0] for p in passes]
        fps = [p[1] for p in passes]
        fp_spreads.append(max(fps) - min(fps))
        common = set(fmaps[0])
        for fm in fmaps[1:]:
            common &= set(fm)
        for fid in common:
            total_findings += 1
            votes = [fm[fid] for fm in fmaps]
            if all(votes) or not any(votes):
                unanimous_findings += 1
            for a, b in combinations(votes, 2):
                if a == b:
                    agree += 1
                    if a:
                        both_yes += 1
                    else:
                        both_no += 1
                else:
                    disagree += 1
                    yes_no += 1
    if not n_runs:
        sys.exit("no runs with >=2 gradings found — run --prepare first, then "
                 "spawn the regrade cells")
    pairs = agree + disagree
    po = agree / pairs
    # chance agreement from pooled marginal prevalence of "found"
    p_yes = (2 * both_yes + yes_no) / (2 * pairs)
    pe = p_yes ** 2 + (1 - p_yes) ** 2
    kappa = (po - pe) / (1 - pe) if pe < 1 else 1.0
    print(f"runs with multiple gradings : {n_runs}")
    print(f"finding-verdict pairs       : {pairs}")
    print(f"percent agreement           : {po:.1%}")
    print(f"Cohen's kappa (pooled)      : {kappa:.3f}")
    print(f"unanimous findings          : {unanimous_findings}/{total_findings} "
          f"({unanimous_findings/total_findings:.1%})")
    if fp_spreads:
        print(f"false-positive count spread : mean {sum(fp_spreads)/len(fp_spreads):.2f} "
              f"max {max(fp_spreads)} (per response, across passes)")
    print("\nInterpretation: kappa > 0.8 = grading noise is small; 0.6-0.8 = "
          "report CIs must include grader variance; < 0.6 = grader needs work "
          "before leaderboard gaps can be trusted.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--experiment")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--k", type=int, default=3,
                    help="total gradings per run incl. the original (default 3)")
    args = ap.parse_args()
    if args.prepare == args.report:
        ap.error("pass exactly one of --prepare / --report")
    (prepare if args.prepare else report)(args)


if __name__ == "__main__":
    main()
