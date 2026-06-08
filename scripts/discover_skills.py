#!/usr/bin/env python3
"""
Discover SKILL.md files in skills/ and produce/update skills.json manifest.

Scans the skills/ directory tree for SKILL.md files and generates a manifest
mapping human-readable names to paths. Existing entries in skills.json are
preserved; new discoveries are added with enabled=false so the user can
review and enable them.

Usage:
    python3 scripts/discover_skills.py              # print discovered skills
    python3 scripts/discover_skills.py --update      # update skills.json
"""

import json
import re
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJ_ROOT / "skills"
MANIFEST_PATH = PROJ_ROOT / "skills.json"


def derive_name(skill_path: Path) -> str:
    """Derive a short, unique name from a SKILL.md path.

    Strategy: walk up from the SKILL.md, collecting meaningful directory names
    until we hit the skills/ root. Skip generic names like 'skills' and 'plugins'.
    """
    rel = skill_path.relative_to(SKILLS_DIR)
    parts = list(rel.parts[:-1])  # drop SKILL.md

    # Filter out generic directory names
    generic = {"skills", "plugins"}
    meaningful = [p for p in parts if p not in generic]

    if not meaningful:
        return skill_path.parent.name

    # Use last 2 meaningful parts joined by /
    if len(meaningful) >= 2:
        return f"{meaningful[0]}/{meaningful[-1]}"
    return meaningful[0]


def read_first_line_description(skill_path: Path) -> str:
    """Read the first non-empty, non-heading line as a description hint."""
    try:
        with open(skill_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Skip markdown headings and frontmatter
                if line.startswith("#") or line.startswith("---"):
                    continue
                # Return first meaningful line, truncated
                return line[:120]
    except Exception:
        pass
    return ""


def discover() -> list[dict]:
    """Find all SKILL.md files under skills/."""
    found = []
    for skill_path in sorted(SKILLS_DIR.rglob("SKILL.md")):
        rel_path = str(skill_path.relative_to(PROJ_ROOT))
        name = derive_name(skill_path)
        desc = read_first_line_description(skill_path)
        found.append({
            "name": name,
            "path": rel_path,
            "description": desc,
        })
    return found


def load_manifest() -> dict:
    """Load existing skills.json or return empty structure."""
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {
        "description": "Skill manifest for the Solidity security audit benchmark. "
                       "Each entry maps a readable name to a SKILL.md path. "
                       "Set enabled=true for skills to include in benchmarks.",
        "skills": {},
    }


def update_manifest(discovered: list[dict]) -> dict:
    """Merge discovered skills into the manifest, preserving existing entries."""
    manifest = load_manifest()
    existing_paths = {s["path"] for s in manifest["skills"].values()}

    for entry in discovered:
        if entry["path"] in existing_paths:
            continue

        name = entry["name"]
        # Deduplicate names by appending a suffix
        base_name = name
        counter = 2
        while name in manifest["skills"]:
            name = f"{base_name}-{counter}"
            counter += 1

        manifest["skills"][name] = {
            "path": entry["path"],
            "enabled": False,
            "description": entry["description"],
        }

    return manifest


def main():
    do_update = "--update" in sys.argv

    discovered = discover()
    print(f"Found {len(discovered)} SKILL.md files:\n")

    for entry in discovered:
        print(f"  {entry['name']:<50} {entry['path']}")

    if do_update:
        manifest = update_manifest(discovered)
        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
        enabled = sum(1 for s in manifest["skills"].values() if s.get("enabled"))
        total = len(manifest["skills"])
        print(f"\nUpdated {MANIFEST_PATH} ({total} skills, {enabled} enabled)")
        print("Edit skills.json to set enabled=true for skills you want to benchmark.")
    else:
        print(f"\nRun with --update to write/update skills.json")


if __name__ == "__main__":
    main()
