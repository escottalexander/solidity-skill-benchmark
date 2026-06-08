#!/usr/bin/env python3
"""
Import FORGE-Curated VFP data into the benchmark eval format.

Splits each VFP into:
  - evals/{eval_id}/contracts/*.sol   (source only - what the skill sees)
  - evals/{eval_id}/findings.json     (ground truth - used for grading only)
  - evals/{eval_id}/metadata.json     (project name, severity counts, etc.)

This separation is critical: skills must ONLY see the contract source,
never the findings, to prevent bias.
"""

import json
import os
import sys
from pathlib import Path

FORGE_VFP_DIR = Path(__file__).parent.parent.parent / "FORGE-Curated" / "flatten" / "vfp-vuln"
EVALS_DIR = Path(__file__).parent.parent / "evals"


def import_vfp(vfp_path: Path, evals_dir: Path) -> dict:
    """Import a single VFP file into eval format."""
    with open(vfp_path) as f:
        vfp = json.load(f)

    vfp_id = vfp["vfp_id"]
    affected_files = vfp.get("affected_files", {})
    findings = vfp.get("findings", [])

    # Skip if no source code
    if not affected_files or not any(v.strip() for v in affected_files.values()):
        return None

    # Skip if no findings
    if not findings:
        return None

    eval_dir = evals_dir / vfp_id
    contracts_dir = eval_dir / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    # Write contract source files (what the skill will see)
    for filename, source in affected_files.items():
        if source and source.strip():
            # Sanitize filename - just use the base name
            safe_name = Path(filename).name
            with open(contracts_dir / safe_name, "w") as f:
                f.write(source)

    # Write findings (ground truth for grading - skill never sees this)
    ground_truth = []
    for finding in findings:
        ground_truth.append({
            "id": finding["id"],
            "title": finding["title"],
            "severity": finding["severity"],
            "description": finding["description"],
            "cwe_categories": finding.get("category", {}),
            "location": finding.get("location", []),
            "files": finding.get("files", []),
        })

    with open(eval_dir / "findings.json", "w") as f:
        json.dump(ground_truth, f, indent=2)

    # Write metadata
    severity_counts = {}
    for finding in findings:
        sev = finding.get("severity", "Unknown")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    metadata = {
        "eval_id": vfp_id,
        "project_name": vfp.get("project_name", ""),
        "num_contracts": len([f for f, s in affected_files.items() if s and s.strip()]),
        "num_findings": len(findings),
        "severity_counts": severity_counts,
        "contract_files": [Path(f).name for f in affected_files.keys() if affected_files[f] and affected_files[f].strip()],
        "source": "FORGE-Curated",
        "source_file": vfp_path.name,
    }

    with open(eval_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    return metadata


def build_registry(evals_dir: Path):
    """Build evals.json registry from all imported evals."""
    evals = []
    for eval_dir in sorted(evals_dir.iterdir()):
        meta_path = eval_dir / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                evals.append(json.load(f))

    registry = {
        "total_evals": len(evals),
        "total_findings": sum(e["num_findings"] for e in evals),
        "severity_breakdown": {},
        "evals": evals,
    }

    for e in evals:
        for sev, count in e["severity_counts"].items():
            registry["severity_breakdown"][sev] = registry["severity_breakdown"].get(sev, 0) + count

    with open(evals_dir / "evals.json", "w") as f:
        json.dump(registry, f, indent=2)

    return registry


def main():
    if not FORGE_VFP_DIR.exists():
        print(f"Error: FORGE-Curated not found at {FORGE_VFP_DIR}")
        print("Clone it first: git clone https://github.com/shenyimings/FORGE-Curated.git")
        sys.exit(1)

    vfp_files = sorted(FORGE_VFP_DIR.glob("vfp_*.json"))
    print(f"Found {len(vfp_files)} VFP files")

    imported = 0
    skipped = 0

    for vfp_path in vfp_files:
        result = import_vfp(vfp_path, EVALS_DIR)
        if result:
            imported += 1
            print(f"  Imported {result['eval_id']}: {result['project_name']} "
                  f"({result['num_contracts']} contracts, {result['num_findings']} findings)")
        else:
            skipped += 1

    print(f"\nImported: {imported}, Skipped: {skipped}")

    registry = build_registry(EVALS_DIR)
    print(f"\nRegistry: {registry['total_evals']} evals, {registry['total_findings']} findings")
    print(f"Severities: {registry['severity_breakdown']}")


if __name__ == "__main__":
    main()
