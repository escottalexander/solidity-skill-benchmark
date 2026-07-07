#!/usr/bin/env python3
"""Deterministic renderer for the frozen prompt templates in agents/prompts/.

Every subagent prompt used by the benchmark MUST come from a template file
rendered by this script (directly or via prepare_run.py) — never hand-written
by the orchestrator. Rendering is strict in both directions: unresolved
{{PLACEHOLDER}}s and unused variables are both errors, so a template/caller
mismatch fails loudly instead of silently drifting.

The template version is "<filename>@<sha256[:12]>" of the template bytes; it is
recorded in run_metadata.json so any two runs can be proven prompt-identical.

Usage:
  python3 scripts/render_prompt.py <template> --var KEY=VALUE ... [-o OUT]
  python3 scripts/render_prompt.py agents/prompts/grader.md \
      --var FINDINGS_JSON_PATH=/abs/findings.json \
      --var RESPONSE_MD_PATH=/abs/response.md \
      --var GRADING_JSON_PATH=/abs/grading.json

Also importable: render(template_path, mapping) -> (text, version).
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def template_version(template_path) -> str:
    data = Path(template_path).read_bytes()
    return f"{Path(template_path).name}@{hashlib.sha256(data).hexdigest()[:12]}"


def render(template_path, mapping) -> tuple:
    """Render a template with {{KEY}} placeholders. Strict: every placeholder
    must be supplied and every supplied key must be used."""
    text = Path(template_path).read_text()
    needed = set(PLACEHOLDER.findall(text))
    supplied = set(mapping)
    missing = needed - supplied
    unused = supplied - needed
    if missing:
        raise ValueError(f"{template_path}: missing variables: {sorted(missing)}")
    if unused:
        raise ValueError(f"{template_path}: unused variables: {sorted(unused)}")
    rendered = PLACEHOLDER.sub(lambda m: str(mapping[m.group(1)]), text)
    leftover = PLACEHOLDER.findall(rendered)
    if leftover:
        raise ValueError(f"{template_path}: unresolved after render: {leftover}")
    return rendered, template_version(template_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("--var", action="append", default=[],
                    help="KEY=VALUE (repeatable)")
    ap.add_argument("-o", "--out", help="write rendered prompt here (default stdout)")
    args = ap.parse_args()

    mapping = {}
    for kv in args.var:
        if "=" not in kv:
            ap.error(f"--var must be KEY=VALUE, got: {kv}")
        k, v = kv.split("=", 1)
        mapping[k] = v

    text, version = render(args.template, mapping)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}  ({version})", file=sys.stderr)
    else:
        sys.stdout.write(text)
        print(f"[{version}]", file=sys.stderr)


if __name__ == "__main__":
    main()
