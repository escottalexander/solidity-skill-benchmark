#!/usr/bin/env python3
"""Export the contract sources of an eval set as static HTML pages under
site/contracts/, so the leaderboard can link to exactly the code each eval
audited. Publishes ONLY evals/<id>/contracts/*.sol — never findings.json
(the ground truth stays out of the site).

Usage: python3 scripts/export_contracts.py [--set core_subset]
Writes site/contracts/<eval_id>.html for every eval in the set.
"""
import argparse
import html
import json
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
EVALS_DIR = PROJ_ROOT / "evals"
OUT_DIR = PROJ_ROOT / "site" / "contracts"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{eval_id} — audited contracts</title>
<style>
  :root {{ --bg:#fff; --text:#1a1a2e; --muted:#667; --surface:#f6f7f9; --border:#dde; --accent:#4a6cf7; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1117; --text:#e6e6ef; --muted:#99a; --surface:#181b24; --border:#2a2e3d; --accent:#7a95ff; }}
  }}
  body {{ margin:0 auto; max-width:1100px; padding:2rem 1.5rem; background:var(--bg); color:var(--text);
         font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }}
  h1 {{ font-size:1.4rem; margin:0 0 0.25rem; }}
  h2 {{ font-size:1rem; margin:2rem 0 0.5rem; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }}
  .meta, footer {{ color:var(--muted); font-size:0.9rem; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  nav {{ margin:1rem 0; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:0.85rem; }}
  nav a {{ margin-right:1rem; }}
  pre {{ background:var(--surface); border:1px solid var(--border); border-radius:8px;
        padding:1rem; overflow-x:auto; font-size:0.8rem; line-height:1.45; }}
</style>
</head>
<body>
<p><a href="../index.html">&larr; leaderboard</a></p>
<h1>{eval_id}</h1>
<p class="meta">{project} &middot; {nfiles} contract file{plural} &middot; the exact sources given to every
auditor run of this eval in the Solidity Skill Benchmark.</p>
<nav>{nav}</nav>
{sections}
<footer><p>Ground-truth findings for this eval are intentionally not published.</p></footer>
</body>
</html>
"""


def export_eval(eval_id: str) -> bool:
    cdir = EVALS_DIR / eval_id / "contracts"
    if not cdir.is_dir():
        return False
    meta_p = EVALS_DIR / eval_id / "metadata.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    files = sorted(p for p in cdir.rglob("*.sol") if p.is_file())
    if not files:
        return False

    nav, sections = [], []
    for p in files:
        rel = p.relative_to(cdir).as_posix()
        anchor = rel.replace("/", "-")
        nav.append(f'<a href="#{html.escape(anchor)}">{html.escape(rel)}</a>')
        code = html.escape(p.read_text(errors="replace"))
        sections.append(f'<section id="{html.escape(anchor)}"><h2>{html.escape(rel)}</h2>'
                        f"<pre><code>{code}</code></pre></section>")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{eval_id}.html").write_text(PAGE.format(
        eval_id=html.escape(eval_id),
        project=html.escape(str(meta.get("project_name", ""))),
        nfiles=len(files),
        plural="" if len(files) == 1 else "s",
        nav="".join(nav),
        sections="\n".join(sections),
    ))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="core_subset",
                    help="eval-set registry under evals/ (default: core_subset)")
    args = ap.parse_args()
    ids = [e["eval_id"] for e in
           json.loads((EVALS_DIR / f"{args.set}.json").read_text())["evals"]]
    done = [eid for eid in ids if export_eval(eid)]
    skipped = sorted(set(ids) - set(done))
    print(f"exported {len(done)}/{len(ids)} evals to {OUT_DIR}")
    if skipped:
        print("skipped (no contracts):", ", ".join(skipped))


if __name__ == "__main__":
    main()
