#!/usr/bin/env python3
"""
Run a single skill (or baseline) against a single eval using claude -p.

Creates an isolated temp workspace containing ONLY:
  - contracts/*.sol  (the files to audit)
  - .claude/skills/<name>/SKILL.md  (the skill under test, if not baseline)

The agent runs inside this workspace with Read/Glob/Grep tools and discovers
the contracts on its own. It cannot ascend to the eval framework because the
workspace is a standalone temp directory with no parent link to the project.

Usage:
  python3 scripts/run_eval.py <skill_name_or_path> <eval_id> [--skip-if-exists]
  python3 scripts/run_eval.py --baseline <eval_id> [--skip-if-exists]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PROJ_ROOT = Path(__file__).parent.parent
MANIFEST = PROJ_ROOT / "skills.json"
MAX_TURNS = 5


def resolve_skill(arg: str) -> tuple[str, str]:
    """Given a skill name or path, return (skill_name, skill_path)."""
    path = Path(arg)
    if path.is_file():
        skill_path = str(path.resolve())
        if MANIFEST.exists():
            rel_path = os.path.relpath(skill_path, PROJ_ROOT)
            with open(MANIFEST) as f:
                manifest = json.load(f)
            for name, info in manifest.get("skills", {}).items():
                if info["path"] == rel_path:
                    return name, skill_path
            parts = rel_path.replace("skills/", "", 1).replace("/SKILL.md", "").split("/")
            generic = {"skills", "plugins"}
            meaningful = [p for p in parts if p not in generic]
            if len(meaningful) >= 2:
                return f"{meaningful[0]}/{meaningful[-1]}", skill_path
            elif meaningful:
                return meaningful[0], skill_path
        return "unknown", skill_path

    if MANIFEST.exists():
        with open(MANIFEST) as f:
            manifest = json.load(f)
        skills = manifest.get("skills", {})
        if arg in skills:
            return arg, str(PROJ_ROOT / skills[arg]["path"])
        for k, v in skills.items():
            if arg in k or k in arg:
                return k, str(PROJ_ROOT / v["path"])

    print(f"Error: '{arg}' is not a file and was not found in skills.json")
    sys.exit(1)


def run_eval(skill_name: str, skill_path: str | None, eval_id: str,
             is_baseline: bool) -> Path:
    """Run a single eval and return the run directory."""
    eval_dir = PROJ_ROOT / "evals" / eval_id
    contracts_dir = eval_dir / "contracts"

    if not contracts_dir.exists():
        print(f"Error: No contracts found at {contracts_dir}")
        sys.exit(1)

    # Create run directory
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    skill_dir_name = skill_name.replace("/", "__")
    run_dir = PROJ_ROOT / "results" / "runs" / skill_dir_name / eval_id / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    # Create isolated temp workspace
    workdir = tempfile.mkdtemp(prefix="eval_")
    try:
        # Copy contracts — the ONLY source material the agent sees
        work_contracts = Path(workdir) / "contracts"
        shutil.copytree(contracts_dir, work_contracts)

        # Install the skill (if not baseline)
        if not is_baseline and skill_path:
            skill_install_dir = Path(workdir) / ".claude" / "skills" / skill_name
            skill_install_dir.mkdir(parents=True)
            shutil.copy2(skill_path, skill_install_dir / "SKILL.md")

        # Build prompt — minimal, let the agent discover via tools
        sol_files = list(work_contracts.glob("*.sol"))
        file_list = "\n".join(f"  - contracts/{f.name}" for f in sol_files)

        prompt = f"""You are performing a security audit of Solidity smart contract(s). Read each file, then identify all vulnerabilities you can find. For each vulnerability, provide:
1. A clear title
2. Severity (Critical/High/Medium/Low/Informational)
3. Description of the vulnerability
4. The affected file(s) and line(s)
5. Recommended fix

Be thorough. Focus on real, exploitable vulnerabilities — not gas optimizations or style issues.

Contract files to audit:
{file_list}"""

        print(f"Running {skill_name} against {eval_id}...")
        start_time = time.time()

        # Run claude -p from the isolated workspace
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--output-format", "json",
                "--max-turns", str(MAX_TURNS),
                "--allowedTools", "Read,Glob,Grep",
            ],
            capture_output=True,
            text=True,
            cwd=workdir,
            timeout=300,
        )

        end_time = time.time()
        duration = int(end_time - start_time)

        # Save raw output
        with open(run_dir / "raw_response.json", "w") as f:
            f.write(result.stdout)
        if result.stderr:
            with open(run_dir / "stderr.log", "w") as f:
                f.write(result.stderr)

        # Parse response
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            print(f"Warning: Could not parse JSON response")
            data = {}

        # Extract response text
        text = ""
        if isinstance(data, dict):
            text = data.get("result", data.get("response", json.dumps(data, indent=2)))
        elif isinstance(data, list):
            parts = [b.get("text", "") for b in data if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(parts) if parts else json.dumps(data, indent=2)
        else:
            text = str(data)

        with open(run_dir / "response.md", "w") as f:
            f.write(text)

        # Build run metadata
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        model_usage = data.get("modelUsage", {}) if isinstance(data, dict) else {}
        model_name = ""
        model_info = {}
        if model_usage:
            model_name = next(iter(model_usage))
            model_info = model_usage[model_name]

        skill_path_rel = os.path.relpath(skill_path, PROJ_ROOT) if skill_path else ""
        tokens = {
            "input": model_info.get("inputTokens", usage.get("input_tokens", 0)),
            "output": model_info.get("outputTokens", usage.get("output_tokens", 0)),
            "cache_read": model_info.get("cacheReadInputTokens", usage.get("cache_read_input_tokens", 0)),
            "cache_creation": model_info.get("cacheCreationInputTokens", usage.get("cache_creation_input_tokens", 0)),
        }

        metadata = {
            "skill": skill_name,
            "skill_path": skill_path_rel,
            "eval_id": eval_id,
            "timestamp": timestamp,
            "is_baseline": is_baseline,
            "duration_seconds": duration,
            "duration_ms": data.get("duration_ms", 0) if isinstance(data, dict) else 0,
            "duration_api_ms": data.get("duration_api_ms", 0) if isinstance(data, dict) else 0,
            "num_turns": data.get("num_turns", 0) if isinstance(data, dict) else 0,
            "total_cost_usd": data.get("total_cost_usd", 0) if isinstance(data, dict) else 0,
            "model": model_name,
            "tokens": tokens,
        }

        with open(run_dir / "run_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

        # Print summary
        total_tokens = sum(tokens.values())
        print(f"  Model: {model_name}")
        print(f"  Tokens: {total_tokens:,} (in={tokens['input']:,} out={tokens['output']:,} "
              f"cache_read={tokens['cache_read']:,} cache_create={tokens['cache_creation']:,})")
        print(f"  Cost: ${metadata['total_cost_usd']:.4f}")
        print(f"Done: {run_dir} ({duration}s)")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return run_dir


def main():
    parser = argparse.ArgumentParser(description="Run a skill against a single eval")
    parser.add_argument("skill", help="Skill name, path to SKILL.md, or --baseline")
    parser.add_argument("eval_id", help="Eval ID (e.g. vfp_00001)")
    parser.add_argument("--skip-if-exists", action="store_true",
                        help="Skip if results already exist")

    args = parser.parse_args()
    is_baseline = args.skill == "--baseline"

    if is_baseline:
        skill_name = "baseline"
        skill_path = None
    else:
        skill_name, skill_path = resolve_skill(args.skill)

    if args.skip_if_exists:
        skill_dir_name = skill_name.replace("/", "__")
        existing = PROJ_ROOT / "results" / "runs" / skill_dir_name / args.eval_id
        if existing.exists() and any(existing.iterdir()):
            print(f"Skipping {skill_name}/{args.eval_id} (already exists)")
            return

    run_eval(skill_name, skill_path, args.eval_id, is_baseline)


if __name__ == "__main__":
    main()
