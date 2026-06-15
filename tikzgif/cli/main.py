"""Command-line interface for tikzgif."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

from ..api import render
from ..compile import detect_available_engines
from ..exceptions import (
    AssemblyError,
    BoundingBoxError,
    CompilationError,
    ConverterNotFoundError,
    DependencyError,
    InputError,
    LatexNotFoundError,
    RenderError,
    TemplateError,
    TikzGifError,
)
from ..rasterize import BACKEND_PRIORITY
from ..rasterize.backends import _BACKEND_BY_NAME
from ..template import parse_template_from_file

if TYPE_CHECKING:
    from ..rasterize import ConversionBackend

EXIT_SUCCESS = 0
EXIT_COMPILE = 1
EXIT_DEPENDENCY = 2
EXIT_INPUT = 3
EXIT_OUTPUT = 4
EXIT_PARTIAL = 5
EXIT_INTERNAL = 70

#: Stable schema version stamped onto every machine-readable JSON object.
SCHEMA_VERSION = 1

#: Backend names in registry order, used for ``--backend`` choices.
BACKEND_NAMES = list(_BACKEND_BY_NAME)

#: Exit-code table, documented verbatim in help output and ``--help-json``.
EXIT_CODE_TABLE: list[tuple[int, str]] = [
    (0, "success"),
    (1, "LaTeX compilation failed"),
    (2, "missing system dependency"),
    (3, "bad input / template / arguments"),
    (4, "output write/encode failure"),
    (5, "partial success (output produced, >=1 frame failed)"),
    (70, "unexpected internal error (likely a bug)"),
]


def _exit_code_block() -> str:
    """Render the exit-code table as an indented text block."""
    lines = ["Exit codes:"]
    lines.extend(f"  {code:<2d} {desc}" for code, desc in EXIT_CODE_TABLE)
    return "\n".join(lines)


_RENDER_EXAMPLES = (
    "Examples:\n"
    "  # Basic GIF sweep of \\PARAM from 0 to 1 over 90 frames\n"
    "  tikzgif render demo.tex --param t --start 0 --end 1 --frames 90\n"
    "\n"
    "  # MP4 with a fixed bounding box, machine-readable result\n"
    "  tikzgif render demo.tex --format mp4 --bbox 0,0,10,8 --json\n"
    "\n"
    "  # Fast sanity check: only the first and last frame as PNGs\n"
    "  tikzgif render demo.tex --test\n"
    "\n"
    "  # Inspect the template before rendering\n"
    "  tikzgif inspect template demo.tex --param t"
)

_OUTPUT_NOTE = (
    "stdout carries the result; pass --json for a machine-readable object, "
    "--quiet to silence status, --output-path-only for just the path."
)


def _render_epilog() -> str:
    """Compose the render subparser epilog (examples + exit codes + note)."""
    return f"{_RENDER_EXAMPLES}\n\n{_exit_code_block()}\n\n{_OUTPUT_NOTE}"


_TOP_EPILOG = (
    "Run 'tikzgif render --help' for rendering options or "
    "'tikzgif inspect --help' to probe engines, backends, and templates.\n"
    "Pass --help-json for a machine-readable description of every command."
)


def _resolve_version() -> str:
    """Return the installed package version, single-sourced from the package.

    Reads the distribution metadata first so a built/installed wheel reports
    its real version; falls back to the in-tree ``__version__`` when running
    from a source checkout that is not installed.
    """
    try:
        return _pkg_version("tikzgif")
    except PackageNotFoundError:
        from .. import __version__

        return __version__


class _ArgumentParser(argparse.ArgumentParser):
    """``ArgumentParser`` that maps usage errors to the bad-input exit code.

    Argparse's default ``error()`` exits with status ``2``; here that
    status is reserved for missing system dependencies, so usage errors
    are routed to the bad-input exit code instead.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_INPUT, f"{self.prog}: error: {message}\n")
        raise SystemExit(EXIT_INPUT)


class _HelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """Help formatter that shows defaults only for value-taking flags.

    Combines default-display with raw (verbatim) description/epilog
    formatting so the examples and exit-code table keep their layout.
    The ``(default: ...)`` suffix is appended only for flags that take a
    value and have a non-``None`` default; flag-style actions
    (``store_true``/``store_false``/``count``/``version``/``help``) and
    actions whose default is ``None`` are left untouched to avoid noisy
    ``(default: None)`` / ``(default: False)`` clutter.
    """

    def _get_help_string(self, action: argparse.Action) -> str | None:
        help_text = action.help
        if help_text is None:
            return None
        if "%(default)" in help_text:
            return help_text
        if action.default is None or action.default is argparse.SUPPRESS:
            return help_text
        # ``nargs == 0`` covers store_true/store_false/count and similar
        # value-less flags; their boolean/zero defaults are noise.
        if action.nargs == 0:
            return help_text
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            return help_text
        return help_text + " (default: %(default)s)"


def _exit_code_for(exc: Exception) -> int:
    """Map an exception to its documented process exit code.

    The mapping mirrors the exit-code table documented for the CLI.
    ``RenderError`` is dispatched by its ``stage`` attribute when set.

    Args:
        exc: The exception raised while running a command.

    Returns:
        The process exit code for *exc*.
    """
    if isinstance(exc, CompilationError):
        return EXIT_COMPILE
    if isinstance(exc, RenderError):
        stage = getattr(exc, "stage", "") or ""
        if stage == "compile":
            return EXIT_COMPILE
        if stage == "assembly":
            return EXIT_OUTPUT
        return EXIT_COMPILE
    if isinstance(exc, (LatexNotFoundError, ConverterNotFoundError, DependencyError)):
        return EXIT_DEPENDENCY
    if isinstance(exc, (InputError, TemplateError, BoundingBoxError)):
        return EXIT_INPUT
    if isinstance(exc, AssemblyError):
        return EXIT_OUTPUT
    return EXIT_INTERNAL


def _print_remediation(exc: TikzGifError) -> None:
    """Print indented follow-on remediation lines to stderr.

    The lines use a stable ``^  (install|hint|engine|frame|log): `` shape so
    humans can skim them and agents can regex them.

    Args:
        exc: The tikzgif error carrying remediation attributes, if any.
    """
    if isinstance(exc, (ConverterNotFoundError, DependencyError)):
        install_hint = getattr(exc, "install_hint", "")
        if install_hint:
            print(f"  install: {install_hint}", file=sys.stderr)
    if isinstance(exc, LatexNotFoundError) and exc.engine:
        print(f"  engine: {exc.engine}", file=sys.stderr)
    if isinstance(exc, CompilationError):
        if exc.frame_index is not None:
            print(f"  frame: {exc.frame_index}", file=sys.stderr)
        if exc.log_content:
            tail = exc.log_content.splitlines()[-15:]
            print(
                f"  log: {' / '.join(line.strip() for line in tail)}", file=sys.stderr
            )


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    """Parse a comma-separated bounding-box string.

    Args:
        raw: String in the form ``"xmin,ymin,xmax,ymax"``, or ``None``.

    Returns:
        Tuple of four floats, or ``None`` if *raw* is ``None``.

    Raises:
        InputError: If the string is malformed, or if the ordering constraint
            ``xmax > xmin and ymax > ymin`` is violated.
    """
    if raw is None:
        return None
    pieces = [p.strip() for p in raw.split(",")]
    if len(pieces) != 4:
        raise InputError("--bbox must be 'xmin,ymin,xmax,ymax'")
    try:
        xmin, ymin, xmax, ymax = (float(p) for p in pieces)
    except ValueError as exc:
        raise InputError("--bbox values must be numeric") from exc
    if xmax <= xmin or ymax <= ymin:
        raise InputError(
            "--bbox must be 'xmin,ymin,xmax,ymax' with xmax>xmin and ymax>ymin "
            f"(got xmin={xmin}, ymin={ymin}, xmax={xmax}, ymax={ymax})"
        )
    return xmin, ymin, xmax, ymax


def _print_size(size_bytes: int) -> str:
    """Format *size_bytes* as a human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _backend_availability() -> dict[str, bool]:
    """Map each rasterization backend name to its availability flag.

    Single source for both the human and ``--json`` ``inspect backends``
    output so the two never diverge.
    """
    availability: dict[str, bool] = {}
    for backend_cls in BACKEND_PRIORITY:
        cls = cast("type[ConversionBackend]", backend_cls)
        availability[cls.name] = bool(cls.is_available())
    return availability


def _emit_json(obj: dict[str, Any]) -> None:
    """Print exactly one JSON object to stdout, followed by a newline."""
    print(json.dumps(obj))


def _error_object(exc: Exception) -> dict[str, Any]:
    """Build the machine-readable error object for *exc*.

    Mirrors the human exit code via the shared ``_exit_code_for`` so the
    JSON ``exit_code`` and the process exit code always agree. Typed
    attributes are surfaced under stable keys when present.
    """
    error: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    if isinstance(exc, (ConverterNotFoundError, DependencyError)) and exc.install_hint:
        error["install_hint"] = exc.install_hint
    if isinstance(exc, ConverterNotFoundError) and exc.backend:
        error["backend"] = exc.backend
    if isinstance(exc, DependencyError) and exc.tool:
        error["tool"] = exc.tool
    if isinstance(exc, LatexNotFoundError) and exc.engine:
        error["engine"] = exc.engine
    if isinstance(exc, CompilationError):
        if exc.frame_index is not None:
            error["frame_index"] = exc.frame_index
        if exc.log_content:
            error["log_content"] = exc.log_content
    if isinstance(exc, AssemblyError) and exc.output_format:
        error["output_format"] = exc.output_format
    if isinstance(exc, RenderError) and exc.stage:
        error["stage"] = exc.stage
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "error": error,
        "exit_code": _exit_code_for(exc),
    }


def _emit_error_json(exc: Exception) -> int:
    """Emit the JSON error object for *exc* to stdout and return its code."""
    obj = _error_object(exc)
    _emit_json(obj)
    return int(obj["exit_code"])


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with subcommands."""
    parser = _ArgumentParser(
        prog="tikzgif",
        description="Parameterized TikZ to animation pipeline",
        epilog=_TOP_EPILOG,
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tikzgif {_resolve_version()}",
        help="Show the tikzgif version and exit",
    )
    parser.add_argument(
        "--help-json",
        action="store_true",
        help="Print a machine-readable description of every command and flag, then exit",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="{render,inspect}")

    render_parser = subparsers.add_parser(
        "render",
        help="Render a .tex file into an animation",
        description="Compile a parameterized TikZ .tex file into GIF or MP4.",
        epilog=_render_epilog(),
        formatter_class=_HelpFormatter,
    )
    render_parser.add_argument(
        "tex_file",
        metavar="FILE",
        help="Path to the .tex file containing \\PARAM tokens",
    )
    render_parser.add_argument(
        "--param",
        metavar="NAME",
        default="PARAM",
        help="Token name (without backslash) swept across frames",
    )
    render_parser.add_argument(
        "--start",
        metavar="F",
        type=float,
        default=0.0,
        help="First value of the swept parameter",
    )
    render_parser.add_argument(
        "--end",
        metavar="F",
        type=float,
        default=1.0,
        help="Last value of the swept parameter",
    )
    render_parser.add_argument(
        "--frames",
        metavar="N",
        type=int,
        default=90,
        help="Number of frames to render",
    )
    render_parser.add_argument(
        "--fps",
        metavar="N",
        type=int,
        default=30,
        help="Frames per second in the output",
    )
    render_parser.add_argument(
        "--format",
        choices=["gif", "mp4"],
        default="gif",
        help="Output container format",
    )
    render_parser.add_argument(
        "--quality",
        choices=["web", "presentation", "print"],
        default="presentation",
        help="Quality preset controlling output width/detail",
    )
    render_parser.add_argument(
        "--engine",
        choices=["pdflatex", "xelatex", "lualatex"],
        default=None,
        help="LaTeX engine (omit to auto-detect)",
    )
    render_parser.add_argument(
        "--workers",
        metavar="N",
        type=int,
        default=0,
        help="Parallel workers for compilation and rasterization (0 = auto)",
    )
    render_parser.add_argument(
        "--timeout",
        metavar="SEC",
        type=float,
        default=30.0,
        help="Per-frame compilation timeout in seconds",
    )
    render_parser.add_argument(
        "--dpi",
        metavar="N",
        type=int,
        default=300,
        help="Rasterization resolution in dots per inch",
    )
    render_parser.add_argument(
        "--error-policy",
        choices=["abort", "skip", "retry"],
        default="retry",
        help="How to handle a frame that fails to compile",
    )
    render_parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        default=None,
        help="Output file path (default: <tex name>.<format>)",
    )
    render_parser.add_argument(
        "--raw-pdf-dir",
        metavar="DIR",
        default=None,
        help="Also copy each frame's raw PDF into this directory",
    )
    render_parser.add_argument(
        "--raw-png-dir",
        metavar="DIR",
        default=None,
        help="Also copy each frame's raw PNG into this directory",
    )

    render_parser.add_argument(
        "--bbox",
        metavar="XMIN,YMIN,XMAX,YMAX",
        default=None,
        help="Fixed bounding box applied to every frame",
    )
    render_parser.add_argument(
        "--shell-escape",
        action="store_true",
        help="Pass --shell-escape to the LaTeX engine",
    )
    render_parser.add_argument(
        "--latex-arg",
        metavar="ARG",
        action="append",
        default=[],
        help="Extra argument forwarded to the LaTeX engine (repeatable)",
    )
    render_parser.add_argument(
        "--cache-dir",
        metavar="DIR",
        default=None,
        help="Compilation cache directory (default: platform cache)",
    )
    render_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the cache and recompile every frame",
    )
    render_parser.add_argument(
        "--test",
        action="store_true",
        help="Render only the first and last frames as preview PNGs",
    )

    render_parser.add_argument(
        "--backend",
        choices=BACKEND_NAMES,
        default="pdftoppm",
        help="PDF-to-image rasterization backend",
    )
    render_parser.add_argument(
        "--color-space",
        choices=["rgb", "rgba", "grayscale"],
        default="rgba",
        help="Pixel color space of rendered frames",
    )
    render_parser.add_argument(
        "--background",
        default="white",
        help="Background color name, or 'none' for transparency",
    )
    render_parser.add_argument(
        "--antialias",
        action="store_true",
        help="Enable supersampled anti-aliasing",
    )
    render_parser.add_argument(
        "--antialias-factor",
        metavar="N",
        type=int,
        default=2,
        help="Supersampling multiplier when --antialias is set",
    )
    render_parser.add_argument(
        "--raster-threads",
        metavar="N",
        type=int,
        default=1,
        help="Backend-internal rendering threads per frame",
    )

    render_parser.add_argument(
        "--gif-loop",
        metavar="N",
        type=int,
        default=0,
        help="GIF loop count (0 = loop forever)",
    )
    render_parser.add_argument(
        "--mp4-crf",
        metavar="N",
        type=int,
        default=23,
        help="MP4 constant rate factor (lower = higher quality)",
    )
    render_parser.add_argument(
        "--mp4-preset",
        default="medium",
        help="ffmpeg encoding preset",
    )
    render_parser.add_argument(
        "--mp4-pix-fmt",
        default="yuv420p",
        help="MP4 pixel format",
    )
    render_parser.add_argument(
        "--title",
        metavar="TEXT",
        default="",
        help="Title metadata embedded in the output",
    )
    render_parser.add_argument(
        "--author",
        metavar="TEXT",
        default="",
        help="Author metadata embedded in the output",
    )
    render_parser.add_argument(
        "--comment",
        metavar="TEXT",
        default="Generated by tikzgif",
        help="Comment metadata embedded in the output",
    )
    render_parser.add_argument(
        "--frame-delay-ms",
        metavar="MS",
        type=int,
        default=None,
        help="Override the default inter-frame delay (GIF)",
    )
    render_parser.add_argument(
        "--pause-first-ms",
        metavar="MS",
        type=int,
        default=None,
        help="Extra pause on the first frame (GIF)",
    )
    render_parser.add_argument(
        "--pause-last-ms",
        metavar="MS",
        type=int,
        default=None,
        help="Extra pause on the last frame (GIF)",
    )

    render_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object on stdout and suppress human status lines",
    )
    render_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the status banner, progress counter, and warnings",
    )
    render_parser.add_argument(
        "--output-path-only",
        action="store_true",
        help="Print only the resolved output path(s) on stdout",
    )

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect environment and templates",
        description="Inspect engines, backends, and template metadata.",
        formatter_class=_HelpFormatter,
    )
    inspect_parser.add_argument(
        "--json",
        dest="inspect_json",
        action="store_true",
        help="Emit one JSON object instead of human-readable text",
    )
    inspect_subparsers = inspect_parser.add_subparsers(
        dest="inspect_command",
        metavar="{engines,backends,template}",
    )

    inspect_engines = inspect_subparsers.add_parser(
        "engines",
        help="List detected LaTeX engines",
        formatter_class=_HelpFormatter,
    )
    inspect_engines.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object instead of human-readable text",
    )

    inspect_backends = inspect_subparsers.add_parser(
        "backends",
        help="List raster backends and availability",
        formatter_class=_HelpFormatter,
    )
    inspect_backends.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object instead of human-readable text",
    )

    inspect_template = inspect_subparsers.add_parser(
        "template",
        help="Inspect template parsing details",
        formatter_class=_HelpFormatter,
    )
    inspect_template.add_argument(
        "tex_file",
        metavar="FILE",
        help="Path to the .tex file to inspect",
    )
    inspect_template.add_argument(
        "--param",
        metavar="NAME",
        default="PARAM",
        help="Token name to look for",
    )
    inspect_template.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object instead of human-readable text",
    )

    return parser


def _render_success_json(result: Any) -> dict[str, Any]:
    """Build the render-success JSON object from a ``RenderResult``."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "output_path": str(result.output_path.resolve()),
        "format": result.output_path.suffix.lstrip(".") or None,
        "total_frames": result.total_frames,
        "successful_frames": result.successful_frames,
        "failed_frames": result.failed_frames,
        "cached_frames": result.cached_frames,
        "size_bytes": result.size_bytes,
        "duration_seconds": result.duration_seconds,
        "engine": result.engine,
        "backend": result.backend,
        "failure_details": [
            {"frame": frame, "reason": reason}
            for frame, reason in sorted(result.failure_details)
        ],
        "test_outputs": [str(p.resolve()) for p in result.test_outputs],
    }


def _handle_render(args: argparse.Namespace) -> int:
    """Execute the ``render`` subcommand.

    Honors the additive machine-output flags: ``--json`` emits exactly one
    JSON object on stdout (and nothing else), ``--quiet`` silences status
    output, and ``--output-path-only`` prints just the resolved path(s).
    With no machine flags the default human output is byte-identical to the
    legacy banner / ``Done!`` / test-preview lines.

    Returns:
        Exit code per the documented exit-code table (0 success,
        5 partial success, or an error code).
    """
    as_json = args.json
    path_only = args.output_path_only
    quiet = args.quiet
    # Status output is suppressed by any machine-output mode.
    silent = as_json or path_only or quiet
    # Progress output from the api/compile/assembly layers is written to
    # stderr. In any machine-output mode we both stop emitting the api-side
    # rasterization counter and capture stray stderr writes (e.g. the compile
    # and encode progress lines) so machine output stays clean. Errors still
    # propagate out of the guard and print to the restored stderr below.
    show_progress = not silent
    stderr_guard: contextlib.AbstractContextManager[Any] = (
        contextlib.redirect_stderr(io.StringIO())
        if silent
        else contextlib.nullcontext()
    )

    try:
        bbox = _parse_bbox(args.bbox)
        background = (
            None
            if isinstance(args.background, str) and args.background.lower() == "none"
            else args.background
        )

        if not silent:
            engine_label = args.engine or "auto"
            cache_label = "off" if args.no_cache else "on"
            frame_label = "first+last" if args.test else f"{args.frames}"
            print(
                f"Rendering {frame_label} frames ({args.start} -> {args.end}) | "
                f"engine={engine_label} backend={args.backend} cache={cache_label}"
            )
        with stderr_guard:
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
                bbox=bbox,
                shell_escape=args.shell_escape,
                latex_args=args.latex_arg,
                cache_dir=args.cache_dir,
                no_cache=args.no_cache,
                backend=args.backend,
                color_space=args.color_space,
                background=background,
                antialias=args.antialias,
                antialias_factor=args.antialias_factor,
                raster_threads=args.raster_threads,
                gif_loop_count=args.gif_loop,
                mp4_crf=args.mp4_crf,
                mp4_preset=args.mp4_preset,
                mp4_pixel_format=args.mp4_pix_fmt,
                metadata_title=args.title,
                metadata_author=args.author,
                metadata_comment=args.comment,
                frame_delay_default_ms=args.frame_delay_ms,
                pause_first_ms=args.pause_first_ms,
                pause_last_ms=args.pause_last_ms,
                test_mode=args.test,
                show_progress=show_progress,
            )
    except TikzGifError as exc:
        if as_json:
            return _emit_error_json(exc)
        print(f"Error: {exc}", file=sys.stderr)
        _print_remediation(exc)
        return _exit_code_for(exc)
    except Exception as exc:
        if as_json:
            return _emit_error_json(exc)
        print(f"Unexpected error: {exc}", file=sys.stderr)
        print(
            "  hint: this is likely a bug; please report it at "
            "https://github.com/j-vaught/tikzgif/issues",
            file=sys.stderr,
        )
        return EXIT_INTERNAL

    partial = result.failed_frames > 0 and result.successful_frames > 0

    if as_json:
        _emit_json(_render_success_json(result))
        return EXIT_PARTIAL if partial else EXIT_SUCCESS

    if path_only:
        outputs = result.test_outputs or [result.output_path]
        for p in outputs:
            print(p.resolve())
        return EXIT_PARTIAL if partial else EXIT_SUCCESS

    if result.failed_frames and not quiet:
        print(
            f"\nWarning: {result.failed_frames}/{result.total_frames} frames failed, "
            f"continuing with {result.successful_frames}.",
            file=sys.stderr,
        )
        for frame_idx, reason in sorted(result.failure_details):
            print(f"  Frame {frame_idx}: {reason}", file=sys.stderr)

    if not quiet:
        if result.test_outputs:
            print("Test preview PNGs:")
            for p in result.test_outputs:
                print(f"  {p}")
        else:
            print(
                f"Done! {result.successful_frames} frames -> "
                f"{result.output_path} ({_print_size(result.size_bytes)})"
            )

    # Partial success: output was produced but at least one frame failed.
    # (All-frames-failed already raised RenderError above.)
    if partial:
        return EXIT_PARTIAL
    return EXIT_SUCCESS


def _handle_inspect(
    args: argparse.Namespace, inspect_parser: argparse.ArgumentParser
) -> int:
    """Execute the ``inspect`` subcommand.

    With ``--json`` each subcommand emits one JSON object per the JSON
    contract; otherwise the legacy human-readable layout is preserved.
    Running ``inspect`` with no subcommand is a usage error: a hint listing
    the available subcommands is written to stderr and ``EXIT_INPUT`` is
    returned so scripts can distinguish it from a successful inspection.

    Args:
        args: Parsed arguments for the ``inspect`` subcommand.
        inspect_parser: The ``inspect`` parser, used to print the usage line
            when no subcommand is given.

    Returns:
        Exit code per the documented exit-code table.
    """
    command = args.inspect_command
    # ``--json`` may appear either before the subcommand (parent-level
    # ``inspect_json``) or after it (per-subcommand ``json``); honor both.
    as_json = bool(getattr(args, "json", False)) or bool(
        getattr(args, "inspect_json", False)
    )

    if command is None:
        message = "inspect requires a subcommand: engines, backends, or template"
        if as_json:
            return _emit_error_json(InputError(message))
        inspect_parser.print_usage(sys.stderr)
        print(f"Error: {message}", file=sys.stderr)
        print(
            "  hint: run 'tikzgif inspect --help' to see each subcommand",
            file=sys.stderr,
        )
        return EXIT_INPUT

    try:
        if command == "engines":
            detected = detect_available_engines()
            if as_json:
                _emit_json(
                    {
                        "ok": True,
                        "schema_version": SCHEMA_VERSION,
                        "engines": {
                            engine.value: (str(path) if path is not None else None)
                            for engine, path in detected.items()
                        },
                    }
                )
                return EXIT_SUCCESS
            for engine, path in detected.items():
                if path is None:
                    print(f"{engine.value:10s} missing")
                else:
                    print(f"{engine.value:10s} {path}")
            return EXIT_SUCCESS

        if command == "backends":
            availability = _backend_availability()
            if as_json:
                _emit_json(
                    {
                        "ok": True,
                        "schema_version": SCHEMA_VERSION,
                        "backends": availability,
                    }
                )
                return EXIT_SUCCESS
            for name, available in availability.items():
                status = "available" if available else "missing"
                print(f"{name:12s} {status}")
            return EXIT_SUCCESS

        if command == "template":
            parsed = parse_template_from_file(
                Path(args.tex_file), param_token="\\" + args.param
            )
            if as_json:
                _emit_json(
                    {
                        "ok": True,
                        "schema_version": SCHEMA_VERSION,
                        "template": {
                            "document_class": parsed.document_class,
                            "class_options": list(parsed.class_options),
                            "has_bounding_box": parsed.has_bounding_box,
                            "needs_shell_escape": parsed.needs_shell_escape,
                            "param_token": parsed.param_token,
                            "packages": sorted(parsed.detected_packages),
                        },
                    }
                )
                return EXIT_SUCCESS
            print(f"document_class: {parsed.document_class}")
            print(
                f"class_options: {','.join(parsed.class_options) if parsed.class_options else '(none)'}"
            )
            print(f"has_bounding_box: {parsed.has_bounding_box}")
            print(f"needs_shell_escape: {parsed.needs_shell_escape}")
            print(f"param_token: {parsed.param_token}")
            print(
                f"packages: {','.join(sorted(parsed.detected_packages)) if parsed.detected_packages else '(none)'}"
            )
            return EXIT_SUCCESS
    except TikzGifError as exc:
        if as_json:
            return _emit_error_json(exc)
        print(f"Error: {exc}", file=sys.stderr)
        _print_remediation(exc)
        return _exit_code_for(exc)
    except Exception as exc:
        if as_json:
            return _emit_error_json(exc)
        print(f"Unexpected error: {exc}", file=sys.stderr)
        print(
            "  hint: this is likely a bug; please report it at "
            "https://github.com/j-vaught/tikzgif/issues",
            file=sys.stderr,
        )
        return EXIT_INTERNAL

    print(
        "Error: inspect requires one of: engines, backends, template", file=sys.stderr
    )
    return EXIT_INPUT


def _subparser(parser: argparse.ArgumentParser, name: str) -> argparse.ArgumentParser:
    """Return the named subparser registered on *parser*.

    Args:
        parser: The parent parser holding the subparsers action.
        name: Subcommand name to look up (e.g. ``"inspect"``).

    Returns:
        The subparser for *name*.

    Raises:
        KeyError: If no subparser named *name* is registered.
    """
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices[name]
    raise KeyError(name)


def _action_to_dict(action: argparse.Action) -> dict[str, Any] | None:
    """Describe a single argparse action as a JSON-serializable dict.

    Returns ``None`` for actions that should not appear in the flag list
    (the ``help`` action and the subparsers pseudo-action).
    """
    if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
        return None
    type_name: str | None
    if action.type is None:
        type_name = None
    else:
        type_name = getattr(action.type, "__name__", str(action.type))
    # A value-less flag (store_true/false/count/version) or an ``append``
    # action that accumulates is the practical notion of "repeatable".
    repeatable = isinstance(action, argparse._AppendAction) or action.nargs == "*"
    default = action.default
    if default is argparse.SUPPRESS:
        default = None
    return {
        "names": list(action.option_strings) or [action.dest],
        "dest": action.dest,
        "type": type_name,
        "default": default,
        "choices": list(action.choices) if action.choices is not None else None,
        "metavar": action.metavar,
        "required": bool(getattr(action, "required", False)),
        "repeatable": repeatable,
        "help": action.help,
    }


def _parser_to_dict(parser: argparse.ArgumentParser) -> dict[str, Any]:
    """Describe a parser (and its subcommands) as JSON-serializable data."""
    flags: list[dict[str, Any]] = []
    subcommands: dict[str, Any] = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                subcommands[name] = _parser_to_dict(sub)
            continue
        described = _action_to_dict(action)
        if described is not None:
            flags.append(described)
    described_parser: dict[str, Any] = {
        "prog": parser.prog,
        "description": parser.description,
        "flags": flags,
    }
    if subcommands:
        described_parser["subcommands"] = subcommands
    return described_parser


def _emit_help_json(parser: argparse.ArgumentParser) -> int:
    """Emit a machine-readable description of the whole CLI and return 0.

    Walks the live parser tree so the output never drifts from the actual
    flags, and appends the documented exit-code table plus a short note on
    the ``--json`` result schema.
    """
    payload: dict[str, Any] = {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "program": _parser_to_dict(parser),
        "exit_codes": {str(code): desc for code, desc in EXIT_CODE_TABLE},
        "json_result_schema": {
            "description": (
                "With --json, every command prints exactly one JSON object to "
                "stdout. Objects carry 'ok' (bool) and 'schema_version' (int). "
                "On success render objects include output_path, format, "
                "total_frames, successful_frames, failed_frames, cached_frames, "
                "size_bytes, duration_seconds, engine, backend, failure_details, "
                "and test_outputs. On error, objects carry "
                "{ok:false, error:{type,message,...}, exit_code}."
            ),
            "schema_version": SCHEMA_VERSION,
        },
    }
    _emit_json(payload)
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the appropriate subcommand.

    Args:
        argv: Argument list, or ``None`` to use ``sys.argv``.

    Returns:
        Exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "help_json", False):
        return _emit_help_json(parser)

    if args.command == "render":
        return _handle_render(args)

    if args.command == "inspect":
        inspect_parser = _subparser(parser, "inspect")
        return _handle_inspect(args, inspect_parser)

    parser.print_help()
    return 0


def cli_entry() -> None:
    """Script entry point for the ``tikzgif`` command."""
    sys.exit(main())
