#!/usr/bin/env python3
"""
Select a diverse core subset (~25) of evals from the 300 FORGE-Curated evals.

Selection criteria:
1. Cover different CWE vulnerability classes
2. Mix of severities (Critical, High, Medium)
3. Mix of contract sizes (1 contract vs multiple)
4. Mix of finding counts (1 finding vs many)
5. No duplicate projects (one eval per audit report)

Output: evals/core_subset.json
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent.parent / "evals"


def load_all_evals():
    """Load metadata and findings for all 300 evals."""
    with open(EVALS_DIR / "evals.json") as f:
        registry = json.load(f)

    evals = []
    for entry in registry["evals"]:
        eid = entry["eval_id"]
        findings_path = EVALS_DIR / eid / "findings.json"
        if not findings_path.exists():
            continue

        with open(findings_path) as f:
            findings = json.load(f)

        # Collect all CWE categories (flatten across priority levels)
        cwes = set()
        for finding in findings:
            for level_cwes in finding.get("cwe_categories", {}).values():
                for c in level_cwes:
                    cwes.add(c)

        severities = set()
        for finding in findings:
            severities.add(finding["severity"])

        evals.append({
            "eval_id": eid,
            "project_name": entry["project_name"],
            "num_contracts": entry["num_contracts"],
            "num_findings": entry["num_findings"],
            "severity_counts": entry.get("severity_counts", {}),
            "contract_files": entry.get("contract_files", []),
            "cwes": cwes,
            "severities": severities,
            "findings_summary": [
                {"title": f["title"], "severity": f["severity"]}
                for f in findings
            ],
        })

    return evals


def select_core_subset(evals):
    """
    Greedy selection algorithm:
    1. First, ensure we pick evals that cover rare CWE categories and
       all severity levels.
    2. Enforce one eval per project (deduplicate).
    3. Balance contract count buckets (single vs multi).
    4. Balance finding count buckets (1, 2-3, 4+).
    """
    selected = []
    selected_ids = set()
    selected_projects = set()
    covered_cwes = set()

    # Pre-compute global CWE frequency for rarity scoring
    global_cwe_freq = Counter()
    for ev in evals:
        for c in ev["cwes"]:
            global_cwe_freq[c] += 1

    # Classify evals into buckets
    def severity_bucket(ev):
        if "Critical" in ev["severity_counts"]:
            return "has_critical"
        elif "High" in ev["severity_counts"]:
            return "has_high"
        else:
            return "medium_only"

    def contract_bucket(ev):
        if ev["num_contracts"] == 1:
            return "single_contract"
        elif ev["num_contracts"] <= 3:
            return "multi_small"
        else:
            return "multi_large"

    def finding_bucket(ev):
        n = ev["num_findings"]
        if n == 1:
            return "single_finding"
        elif n <= 3:
            return "few_findings"
        elif n <= 6:
            return "moderate_findings"
        else:
            return "many_findings"

    # Score: how many *new* CWEs does this eval bring, weighted by rarity?
    def novelty_score(ev):
        new_cwes = ev["cwes"] - covered_cwes
        if not new_cwes:
            return 0
        # Weight rare CWEs higher (inverse frequency)
        return sum(1.0 / global_cwe_freq[c] for c in new_cwes)

    # --- Phase 1: Seed with mandatory coverage ---
    # We need at least: 4 critical, 6 high-only, 4 medium-only,
    # some multi-contract, some many-findings

    target_buckets = {
        # severity
        "has_critical": 5,
        "has_high": 10,
        "medium_only": 6,
    }
    finding_targets = {
        "single_finding": 5,
        "few_findings": 5,
        "moderate_findings": 5,
        "many_findings": 5,
    }
    contract_targets = {
        "single_contract": 12,
        "multi_small": 6,
        "multi_large": 3,
    }

    severity_counts = Counter()
    finding_counts = Counter()
    contract_counts = Counter()

    def can_pick(ev):
        return (
            ev["eval_id"] not in selected_ids
            and ev["project_name"] not in selected_projects
        )

    def pick(ev, reason):
        selected.append({"eval": ev, "reason": reason})
        selected_ids.add(ev["eval_id"])
        selected_projects.add(ev["project_name"])
        covered_cwes.update(ev["cwes"])
        severity_counts[severity_bucket(ev)] += 1
        finding_counts[finding_bucket(ev)] += 1
        contract_counts[contract_bucket(ev)] += 1

    # Sort evals by novelty (most novel first), breaking ties by more findings
    def rank_key(ev):
        return (-novelty_score(ev), -ev["num_findings"])

    # Iterative greedy: pick the eval that adds the most CWE coverage
    # while balancing bucket constraints
    MAX_PICKS = 27

    for _ in range(MAX_PICKS):
        candidates = [ev for ev in evals if can_pick(ev)]
        if not candidates:
            break

        # Score each candidate: novelty + bucket need bonus
        best = None
        best_score = -1

        for ev in candidates:
            score = novelty_score(ev)

            # Bonus for under-represented severity bucket
            sb = severity_bucket(ev)
            if severity_counts[sb] < target_buckets.get(sb, 0):
                score += 2.0

            # Bonus for under-represented finding bucket
            fb = finding_bucket(ev)
            if finding_counts[fb] < finding_targets.get(fb, 0):
                score += 1.5

            # Bonus for under-represented contract bucket
            cb = contract_bucket(ev)
            if contract_counts[cb] < contract_targets.get(cb, 0):
                score += 1.0

            # Small bonus for having more findings (richer eval)
            score += min(ev["num_findings"], 10) * 0.05

            if score > best_score:
                best_score = score
                best = ev

        if best is None:
            break

        # Build reason string
        new_cwes = best["cwes"] - (covered_cwes - best["cwes"])
        sb = severity_bucket(best)
        fb = finding_bucket(best)
        cb = contract_bucket(best)

        reason_parts = []
        if "Critical" in best["severity_counts"]:
            reason_parts.append(
                f"Critical severity ({best['severity_counts'].get('Critical', 0)} critical findings)"
            )
        if "High" in best["severity_counts"]:
            reason_parts.append(
                f"High severity ({best['severity_counts'].get('High', 0)} high findings)"
            )

        new_cwe_list = sorted(best["cwes"] - (covered_cwes - best["cwes"]))
        if new_cwe_list:
            reason_parts.append(f"New CWEs: {', '.join(new_cwe_list[:5])}")

        reason_parts.append(
            f"{best['num_contracts']} contract(s), {best['num_findings']} finding(s)"
        )

        pick(best, "; ".join(reason_parts))

    return selected


def build_output(selected):
    """Build the core_subset.json output."""
    entries = []
    for item in selected:
        ev = item["eval"]
        entries.append({
            "eval_id": ev["eval_id"],
            "project_name": ev["project_name"],
            "num_contracts": ev["num_contracts"],
            "num_findings": ev["num_findings"],
            "severity_counts": ev["severity_counts"],
            "cwes_covered": sorted(ev["cwes"]),
            "contract_files": ev["contract_files"],
            "selection_reason": item["reason"],
        })

    # Collect covered CWEs
    all_cwes = set()
    for e in entries:
        all_cwes.update(e["cwes_covered"])

    # Summary stats
    severity_summary = Counter()
    for e in entries:
        for sev, count in e["severity_counts"].items():
            severity_summary[sev] += count

    output = {
        "description": "Core subset of evals for the Solidity security audit skill benchmark. "
        "Selected for diversity across CWE categories, severity levels, contract sizes, "
        "and finding counts. One eval per project to avoid duplication.",
        "version": 1,
        "total_evals": len(entries),
        "coverage": {
            "unique_cwes_covered": len(all_cwes),
            "severity_breakdown": dict(severity_summary),
            "unique_projects": len(set(e["project_name"] for e in entries)),
        },
        "skill_tracking": {
            "_comment": "Track which evals have been run per skill. Add skill names as keys, "
            "with lists of eval_ids that have been tested.",
            "example_skill": [],
        },
        "evals": entries,
    }
    return output


def main():
    print("Loading all 300 evals...")
    evals = load_all_evals()
    print(f"Loaded {len(evals)} evals with {sum(len(e['cwes']) for e in evals)} total CWE tags")

    print("\nSelecting core subset...")
    selected = select_core_subset(evals)
    print(f"Selected {len(selected)} evals")

    output = build_output(selected)

    out_path = EVALS_DIR / "core_subset.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {out_path}")
    print(f"\nSummary:")
    print(f"  Total evals: {output['total_evals']}")
    print(f"  Unique CWEs covered: {output['coverage']['unique_cwes_covered']}")
    print(f"  Severity breakdown: {output['coverage']['severity_breakdown']}")
    print(f"  Unique projects: {output['coverage']['unique_projects']}")
    print(f"\nSelected evals:")
    for e in output["evals"]:
        sev_str = ", ".join(f"{k}:{v}" for k, v in e["severity_counts"].items())
        print(f"  {e['eval_id']} | {sev_str:20s} | {e['num_contracts']}c {e['num_findings']}f | {e['project_name'][:60]}")


if __name__ == "__main__":
    main()
