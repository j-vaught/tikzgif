"""
CLI commands for the template subsystem.

Usage:
    tikzgif templates list [--domain <domain>]
    tikzgif templates preview <name> [--param K=5.0]
    tikzgif templates render <name> [--param K=0:10:0.5]
    tikzgif templates new <name> [--domain <domain>]
    tikzgif templates export <name> [--output <file.tex>]
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

from ..template_registry import get_registry
from ..template_schema import Template, TemplateMeta


_RANGE_RE = re.compile(r"^([\w]+)=([\d.eE\-+]+):([\d.eE\-+]+):([\d.eE\-+]+)$")
_SCALAR_RE = re.compile(r"^([\w]+)=([\d.eE\-+]+)$")


def parse_param_arg(raw: str) -> tuple[str, Any]:
    m = _RANGE_RE.match(raw)
    if m:
        return m.group(1), {
            "min": float(m.group(2)),
            "max": float(m.group(3)),
            "step": float(m.group(4)),
        }
    m = _SCALAR_RE.match(raw)
    if m:
        return m.group(1), float(m.group(2))
    raise ValueError(f"Cannot parse param specification: '{raw}'")


def _format_template_table(metas: list[TemplateMeta]) -> str:
    if not metas:
        return "  (no templates found)\n"
    name_w = max(len(m.name) for m in metas)
    domain_w = max(len(m.domain) for m in metas)
    lines = []
    header = f"  {'Name':<{name_w}}   {'Domain':<{domain_w}}   Description"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for m in metas:
        desc = (m.title or m.description or "")[:60]
        lines.append(f"  {m.name:<{name_w}}   {m.domain:<{domain_w}}   {desc}")
    return "\n".join(lines) + "\n"


_SKELETON = textwrap.dedent(r"""
%%--- TIKZGIF META ---
%% name: {name}
%% title: {title}
%% description: A new template.
%% author: {author}
%% version: 1.0.0
%% domain: {domain}
%% tags: []
%% engine: pdflatex
%% tikz_libraries: []
%% latex_packages: [tikz]
%% params:
%%   - name: t
%%     type: float
%%     default: 0.0
%%     min: 0.0
%%     max: 1.0
%%     step: 0.05
%%     sweep: true
%%     description: Animation parameter
%% fps: 15
%% frames: 20
%%--- END META ---
\documentclass[border=5pt,tikz]{{standalone}}
\usepackage{{tikz}}
\begin{{document}}
\begin{{tikzpicture}}
\pgfmathsetmacro{{\t}}{{{{{{{ t }}}}}}}
\draw[thick, blue] (0,0) -- ({{\t * 5}}, 0);
\filldraw[red] ({{\t * 5}}, 0) circle (3pt);
\end{{tikzpicture}}
\end{{document}}
""").lstrip()


def cmd_list(args: argparse.Namespace) -> int:
    reg = get_registry()
    metas = reg.list_templates(domain=getattr(args, "domain", None))
    print(_format_template_table(metas))
    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    reg = get_registry()
    try:
        tpl = reg.get(args.name)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    overrides: dict[str, Any] = {}
    for raw in (args.param or []):
        k, v = parse_param_arg(raw)
        if isinstance(v, dict):
            overrides[k] = (v["min"] + v["max"]) / 2
        else:
            overrides[k] = v
    vals = {p.name: overrides.get(p.name, p.default) for p in tpl.meta.params}
    tex_source = tpl.render_frame(vals)
    import tempfile, subprocess, shutil
    with tempfile.TemporaryDirectory(prefix="tikzgif_preview_") as tmpdir:
        tex_path = Path(tmpdir) / "preview.tex"
        tex_path.write_text(tex_source, encoding="utf-8")
        result = subprocess.run(
            [tpl.meta.engine, "-interaction=nonstopmode", "preview.tex"],
            cwd=tmpdir, capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            print("LaTeX compilation failed:", file=sys.stderr)
            return 1
        pdf_path = Path(tmpdir) / "preview.pdf"
        if pdf_path.exists():
            out = Path.cwd() / f"{args.name.replace('.', '_')}_preview.pdf"
            shutil.copy2(pdf_path, out)
            print(f"Preview saved to: {out}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    reg = get_registry()
    try:
        tpl = reg.get(args.name)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    overrides: dict[str, Any] = {}
    for raw in (args.param or []):
        k, v = parse_param_arg(raw)
        if not isinstance(v, dict):
            overrides[k] = v
    n_frames = getattr(args, "frames", None) or tpl.meta.recommended_frames
    print(f"Generating {n_frames} frames...")
    for idx, vals, tex in tpl.generate_all_frames(overrides=overrides, n_frames=n_frames):
        if idx % 10 == 0 or idx == n_frames - 1:
            print(f"  Frame {idx:>4d}")
    print("Frame generation complete.")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    domain = getattr(args, "domain", "custom")
    author = getattr(args, "author", "")
    title = args.name.replace(".", " ").replace("_", " ").title()
    skeleton = _SKELETON.format(name=args.name, title=title, domain=domain, author=author)
    out_dir = Path.cwd() / ".tikzgif" / "templates"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.name.replace('.', '_')}.tex"
    if out_path.exists():
        print(f"Error: {out_path} already exists.", file=sys.stderr)
        return 1
    out_path.write_text(skeleton, encoding="utf-8")
    print(f"Template skeleton created: {out_path}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    reg = get_registry()
    try:
        tpl = reg.get(args.name)
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    overrides: dict[str, Any] = {}
    for raw in (args.param or []):
        k, v = parse_param_arg(raw)
        if isinstance(v, dict):
            overrides[k] = (v["min"] + v["max"]) / 2
        else:
            overrides[k] = v
    vals = {p.name: overrides.get(p.name, p.default) for p in tpl.meta.params}
    tex_source = tpl.render_frame(vals)
    out_path = getattr(args, "output", None)
    out = Path(out_path) if out_path else Path.cwd() / f"{args.name.replace('.', '_')}_export.tex"
    out.write_text(tex_source, encoding="utf-8")
    print(f"Exported to: {out}")
    return 0


def build_templates_parser(subparsers: argparse._SubParsersAction) -> None:
    tpl_parser = subparsers.add_parser("templates", help="Manage templates")
    tpl_sub = tpl_parser.add_subparsers(dest="templates_cmd")

    p = tpl_sub.add_parser("list", help="List templates")
    p.add_argument("--domain", default=None)
    p.set_defaults(func=cmd_list)

    p = tpl_sub.add_parser("preview", help="Single static frame")
    p.add_argument("name")
    p.add_argument("--param", action="append")
    p.set_defaults(func=cmd_preview)

    p = tpl_sub.add_parser("render", help="Full animation")
    p.add_argument("name")
    p.add_argument("--param", action="append")
    p.add_argument("--fps", type=int, default=None)
    p.add_argument("--frames", type=int, default=None)
    p.add_argument("--output", "-o", default=None)
    p.set_defaults(func=cmd_render)

    p = tpl_sub.add_parser("new", help="Scaffold new template")
    p.add_argument("name")
    p.add_argument("--domain", default="custom")
    p.add_argument("--author", default="")
    p.set_defaults(func=cmd_new)

    p = tpl_sub.add_parser("export", help="Export as standalone .tex")
    p.add_argument("name")
    p.add_argument("--param", action="append")
    p.add_argument("--output", "-o", default=None)
    p.set_defaults(func=cmd_export)
