"""
CLI command for rendering a parameterized .tex file into an animation.

Usage:
    tikzgif render my_drawing.tex --frames 30 --fps 10 -o output.gif
    tikzgif render my_drawing.tex --start 0 --end 360 --frames 60 --format mp4
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from ..assembly import (
    AnimationAssembler,
    FrameDelay,
    OutputConfig,
    OutputFormat,
    QualityPreset,
)
from ..backends import RenderConfig
from ..compiler import compile_with_bbox_normalization
from ..detection import select_backend
from ..types import CompilationConfig, ErrorPolicy, LatexEngine


_FORMAT_MAP = {
    "gif": OutputFormat.GIF,
    "mp4": OutputFormat.MP4,
    "webp": OutputFormat.WEBP,
    "apng": OutputFormat.APNG,
    "svg": OutputFormat.SVG,
}

_QUALITY_MAP = {
    "web": QualityPreset.WEB,
    "presentation": QualityPreset.PRESENTATION,
    "print": QualityPreset.PRINT,
}

_ENGINE_MAP = {
    "pdflatex": LatexEngine.PDFLATEX,
    "xelatex": LatexEngine.XELATEX,
    "lualatex": LatexEngine.LUALATEX,
}

_POLICY_MAP = {
    "abort": ErrorPolicy.ABORT,
    "skip": ErrorPolicy.SKIP,
    "retry": ErrorPolicy.RETRY,
}


def cmd_render(args: argparse.Namespace) -> int:
    """Main handler for ``tikzgif render``."""
    tex_file = Path(args.tex_file)
    if not tex_file.is_file():
        print(f"Error: file not found: {tex_file}", file=sys.stderr)
        return 1

    source = tex_file.read_text(encoding="utf-8")

    # Generate parameter values.
    n = args.frames
    start = args.start
    end = args.end
    if n == 1:
        param_values = [start]
    else:
        param_values = [start + i * (end - start) / (n - 1) for i in range(n)]

    # Build compilation config.
    engine = _ENGINE_MAP[args.engine] if args.engine else LatexEngine.PDFLATEX
    comp_config = CompilationConfig(
        engine=engine,
        error_policy=_POLICY_MAP[args.error_policy],
        max_workers=args.workers,
        timeout_per_frame_s=args.timeout,
        dpi=args.dpi,
    )

    # Compile all frames (two-pass with bbox normalization).
    print(f"Compiling {n} frames ({start} -> {end}) ...")
    frame_results, envelope = compile_with_bbox_normalization(
        source,
        param_values,
        comp_config,
        param_token="\\" + args.param,
    )

    successful = [r for r in frame_results if r.success]
    failed = [r for r in frame_results if not r.success]

    if not successful:
        print("Error: all frames failed to compile.", file=sys.stderr)
        for r in failed[:5]:
            print(f"  Frame {r.index}: {r.error_message}", file=sys.stderr)
        return 1

    if failed:
        print(f"Warning: {len(failed)}/{n} frames failed, continuing with {len(successful)}.",
              file=sys.stderr)

    # Convert PDFs to PNGs.
    print("Converting PDFs to PNGs ...")
    backend = select_backend()
    render_config = RenderConfig(dpi=args.dpi, antialias=False, threads=1)

    with tempfile.TemporaryDirectory(prefix="tikzgif_render_") as tmpdir:
        tmp = Path(tmpdir)
        for result in successful:
            if result.pdf_path and result.pdf_path.exists():
                images = backend.convert(result.pdf_path, render_config)
                if images:
                    png_path = tmp / f"frame_{result.index:06d}.png"
                    images[0].save(str(png_path), format="PNG")
                    result.png_path = png_path

        # Determine output path.
        if args.output:
            output_path = Path(args.output)
        else:
            ext = args.format
            output_path = Path(tex_file.stem + f".{ext}")

        # Build output config.
        delay_ms = int(1000 / args.fps) if args.fps > 0 else 100
        output_config = OutputConfig(
            format=_FORMAT_MAP[args.format],
            output_path=output_path,
            preset=_QUALITY_MAP[args.quality],
            frame_delay=FrameDelay(default_ms=delay_ms),
        )

        # Assemble animation.
        print(f"Assembling {args.format.upper()} ...")
        assembler = AnimationAssembler(output_config)
        result_path = assembler.assemble(frame_results)

    # Summary.
    size_bytes = result_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

    print(f"Done! {len(successful)} frames -> {result_path} ({size_str})")
    return 0


def build_render_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``render`` subcommand and its arguments."""
    p = subparsers.add_parser(
        "render",
        help="Render a .tex file into an animation",
        description="Compile a parameterized TikZ .tex file into an animated GIF, MP4, WebP, or APNG.",
    )
    p.add_argument(
        "tex_file",
        help="Path to the .tex file containing \\PARAM tokens",
    )
    p.add_argument(
        "--param", default="PARAM",
        help="Parameter token name (default: PARAM, looked up as \\PARAM)",
    )
    p.add_argument(
        "--start", type=float, default=0.0,
        help="Start value for the parameter sweep (default: 0)",
    )
    p.add_argument(
        "--end", type=float, default=1.0,
        help="End value for the parameter sweep (default: 1)",
    )
    p.add_argument(
        "--frames", type=int, default=30,
        help="Number of animation frames (default: 30)",
    )
    p.add_argument(
        "--fps", type=int, default=10,
        help="Frames per second (default: 10)",
    )
    p.add_argument(
        "--format", choices=["gif", "mp4", "webp", "apng", "svg"], default="gif",
        help="Output format (default: gif)",
    )
    p.add_argument(
        "--quality", choices=["web", "presentation", "print"], default="presentation",
        help="Quality preset (default: presentation)",
    )
    p.add_argument(
        "--engine", choices=["pdflatex", "xelatex", "lualatex"], default=None,
        help="LaTeX engine (default: auto-detect)",
    )
    p.add_argument(
        "--workers", type=int, default=0,
        help="Parallel compilation workers; 0 = auto (default: 0)",
    )
    p.add_argument(
        "--timeout", type=float, default=30.0,
        help="Timeout per frame in seconds (default: 30)",
    )
    p.add_argument(
        "--dpi", type=int, default=300,
        help="DPI for PDF-to-PNG conversion (default: 300)",
    )
    p.add_argument(
        "--error-policy", choices=["abort", "skip", "retry"], default="retry",
        help="How to handle frame compilation failures (default: retry)",
    )
    p.add_argument(
        "-o", "--output", default=None,
        help="Output file path (default: <input_stem>.<format>)",
    )
    p.set_defaults(func=cmd_render)
