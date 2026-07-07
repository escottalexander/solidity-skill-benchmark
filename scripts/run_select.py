#!/usr/bin/env python3
"""Shared run selection for the analysis scripts (rank_analysis,
baseline_compare, model_compare).

Two modes:
- EXPERIMENTS env set (comma-separated manifest names): cells come from
  results/experiments/<name>.json — the explicit, repetition-aware selection.
  ALL reps of a cell are returned; callers aggregate (mean stats / majority
  vote per finding).
- EXPERIMENTS unset: legacy directory heuristics — latest original-pass run
  per cell (tooling disabled unless asked, no pass-2, no tooling-off 'D' arm,
  no manifest-tagged experiment runs), single grading returned.

Callers:
    import run_select as rs
    gs = rs.cell_gradings("scv-scan", "vfp_00005", model="claude-sonnet-4-6")
    fmap = rs.majority_fmap(gs)      # {finding_id: bool}, found in >=half reps
    stats = rs.mean_summary(gs)      # mean recall/precision/f1/fp across reps
"""
import json
import os
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
RUNS = PROJ / "results" / "runs"
EXP_DIR = PROJ / "results" / "experiments"

EXPERIMENTS = [e for e in os.environ.get("EXPERIMENTS", "").split(",") if e]

_index = None  # (skill_dir, eval_id) -> [run_dir, ...]


def _load_index():
    global _index
    _index = {}
    for name in EXPERIMENTS:
        manifest = json.loads((EXP_DIR / f"{name}.json").read_text())
        for c in manifest["cells"]:
            key = (c["skill"].replace("/", "__") if c["skill"] != "baseline"
                   else "baseline", c["eval_id"])
            _index.setdefault(key, []).append(PROJ / c["run_dir"])


def _meta(run_dir: Path) -> dict:
    mp = run_dir / "run_metadata.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    gp = run_dir / "grading.json"
    if gp.exists():
        try:
            return json.loads(gp.read_text()).get("run_metadata", {}) or {}
        except Exception:
            pass
    return {}


def cell_gradings(skill_dir, eval_id, model=None, tooling="disabled"):
    """All gradings for a cell (list; one per rep in experiment mode, at most
    one in legacy mode)."""
    if EXPERIMENTS:
        if _index is None:
            _load_index()
        out = []
        for run_dir in _index.get((skill_dir, eval_id), []):
            gp = run_dir / "grading.json"
            if not gp.exists():
                continue
            m = _meta(run_dir)
            if model and m.get("model") != model:
                continue
            if tooling and m.get("tooling", "disabled") != tooling:
                continue
            try:
                out.append(json.loads(gp.read_text()))
            except Exception:
                continue
        return out

    d = RUNS / skill_dir / eval_id
    if not d.is_dir():
        return []
    for run in sorted(os.listdir(d), reverse=True):
        gp = d / run / "grading.json"
        if not gp.exists():
            continue
        m = _meta(d / run)
        if m.get("experiment"):
            continue
        if model and m.get("model") != model:
            continue
        if tooling and m.get("tooling", "disabled") != tooling:
            continue
        if m.get("pass") == 2 or run.endswith("D"):
            continue
        try:
            return [json.loads(gp.read_text())]
        except Exception:
            continue
    return []


def majority_fmap(gradings) -> dict:
    """Per-finding verdict across reps: found iff found in >= half the reps."""
    if not gradings:
        return {}
    votes = {}
    for g in gradings:
        for f in g.get("findings", []):
            votes.setdefault(f.get("id"), []).append(bool(f.get("found")))
        # a rep that omitted a finding counts as a miss for it
    n = len(gradings)
    return {fid: sum(v) * 2 >= n for fid, v in votes.items()}


def mean_summary(gradings) -> dict:
    """Mean recall/precision/f1/false_positives across reps."""
    if not gradings:
        return {}
    rs_, ps, fps = [], [], []
    for g in gradings:
        s = g.get("summary", {})
        rs_.append(s.get("recall", 0))
        ps.append(s.get("precision", 0))
        fps.append(s.get("false_positives", 0))
    r = sum(rs_) / len(rs_)
    p = sum(ps) / len(ps)
    f1 = 2 * r * p / (r + p) if (r + p) else 0.0
    return {"recall": r, "precision": p, "f1": f1,
            "false_positives": sum(fps) / len(fps), "reps": len(gradings)}
