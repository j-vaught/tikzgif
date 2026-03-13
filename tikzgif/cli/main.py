"""Main CLI entry point for tikzgif."""

from __future__ import annotations

import argparse
import sys

from ..api import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tikzgif",
        description="Parameterized TikZ to animation pipeline",
    )
    parser.add_argument("--version", action="version", version="tikzgif 0.1.0")

    subparsers = parser.add_subparsers(dest="command")

    p = subparsers.add_parser(
        "render",
        help="Render a .tex file into an animation",
        description="Compile a parameterized TikZ .tex file into GIF or MP4.",
    )
    p.add_argument("tex_file", help="Path to the .tex file containing \\PARAM tokens")
    p.add_argument("--param", default="PARAM")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=1.0)
    p.add_argument("--frames", type=int, default=90)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--format", choices=["gif", "mp4"], default="gif")
    p.add_argument("--quality", choices=["web", "presentation", "print"], default="presentation")
    p.add_argument("--engine", choices=["pdflatex", "xelatex", "lualatex"], default=None)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--dpi", type=int, default=300)
    p.add_argument("--error-policy", choices=["abort", "skip", "retry"], default="retry")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--raw-pdf-dir", default=None)
    p.add_argument("--raw-png-dir", default=None)

    args = parser.parse_args(argv)

    if args.command != "render":
        parser.print_help()
        return 0

    try:
        print(f"Compiling {args.frames} frames ({args.start} -> {args.end}) ...")
        result = render(
            args.tex_file,
            param=args.param,
            start=args.start,
            end=args.end,
            frames=args.frames,
            fps=args.fps,
            format=args.format,
            quality=args.quality,
            engine=args.engine,
            workers=args.workers,
            timeout=args.timeout,
            dpi=args.dpi,
            error_policy=args.error_policy,
            output=args.output,
            raw_pdf_dir=args.raw_pdf_dir,
            raw_png_dir=args.raw_png_dir,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.failed_frames:
        print(
            f"Warning: {result.failed_frames}/{result.total_frames} frames failed, "
            f"continuing with {result.successful_frames}.",
            file=sys.stderr,
        )

    size_bytes = result.size_bytes
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    print(f"Done! {result.successful_frames} frames -> {result.output_path} ({size_str})")
    return 0


def cli_entry() -> None:
    sys.exit(main())
