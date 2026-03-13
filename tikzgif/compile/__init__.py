"""LaTeX compilation stage."""

from .engine import (
    LatexError,
    build_compile_command,
    detect_available_engines,
    detect_packages,
    detect_tikz_libraries,
    format_errors,
    needs_shell_escape,
    parse_log,
    select_engine,
    uses_pgfplots,
)
from .pipeline import compile_frames, compile_single_pass

__all__ = [
    "LatexError",
    "build_compile_command",
    "detect_available_engines",
    "detect_packages",
    "detect_tikz_libraries",
    "format_errors",
    "needs_shell_escape",
    "parse_log",
    "select_engine",
    "uses_pgfplots",
    "compile_frames",
    "compile_single_pass",
]
