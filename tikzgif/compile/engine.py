"""
LaTeX engine detection, selection, and error parsing.

Handles:
  - Auto-detecting which LaTeX engines are installed.
  - Selecting the right engine based on user preference or package requirements.
  - Building the pdflatex/xelatex/lualatex command line.
  - Parsing .log files to extract human-readable error messages.
  - Detecting shell-escape requirements.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from tikzgif.types import LatexEngine


# ---------------------------------------------------------------------------
# Engine detection
# ---------------------------------------------------------------------------

def detect_available_engines() -> dict[LatexEngine, Path | None]:
    """
    Check which LaTeX engines are available on PATH.

    Returns a dict mapping each engine enum to its resolved path,
    or None if not found.
    """
    result: dict[LatexEngine, Path | None] = {}
    for engine in LatexEngine:
        which = shutil.which(engine.value)
        result[engine] = Path(which) if which else None
    return result


def select_engine(
    preferred: LatexEngine | None = None,
    packages: set[str] | None = None,
) -> LatexEngine:
    """
    Select the best available LaTeX engine.

    Priority:
      1. User's explicit preference (if installed).
      2. Package-driven: fontspec/unicode-math require xelatex or lualatex.
      3. Default: pdflatex (fastest for most TikZ work).

    Raises
    ------
    RuntimeError
        If no suitable engine is installed.
    """
    available = detect_available_engines()
    packages = packages or set()

    # Packages that require Unicode engines.
    unicode_packages = {"fontspec", "unicode-math", "luacode", "luatexbase"}
    needs_unicode = bool(packages & unicode_packages)

    # Packages that specifically need LuaLaTeX.
    lua_only = {"luacode", "luatexbase", "tikz-feynman"}
    needs_lua = bool(packages & lua_only)

    if preferred is not None:
        if available.get(preferred) is not None:
            return preferred
        # Preferred engine not available -- fall through to auto.

    if needs_lua:
        if available.get(LatexEngine.LUALATEX):
            return LatexEngine.LUALATEX
        raise RuntimeError(
            "LuaLaTeX is required by detected packages "
            f"({packages & lua_only}) but is not installed."
        )

    if needs_unicode:
        for eng in (LatexEngine.XELATEX, LatexEngine.LUALATEX):
            if available.get(eng):
                return eng
        raise RuntimeError(
            "XeLaTeX or LuaLaTeX is required by detected packages "
            f"({packages & unicode_packages}) but neither is installed."
        )

    # Default: pdflatex is the fastest for pure TikZ.
    if available.get(LatexEngine.PDFLATEX):
        return LatexEngine.PDFLATEX

    # Fallback to anything available.
    for eng, path in available.items():
        if path is not None:
            return eng

    raise RuntimeError(
        "No LaTeX engine found on PATH. Install TeX Live or MiKTeX."
    )


# ---------------------------------------------------------------------------
# Command-line builder
# ---------------------------------------------------------------------------

def build_compile_command(
    engine: LatexEngine,
    tex_path: Path,
    output_dir: Path,
    shell_escape: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    """
    Build the shell command to compile a single .tex file.

    The command runs in non-interactive (nonstopmode) and writes output
    to the specified directory.  This is critical for parallel builds
    where each process needs an isolated output directory.
    """
    cmd = [
        engine.value,
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={output_dir}",
    ]
    if shell_escape:
        cmd.append("--shell-escape")
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(str(tex_path))
    return cmd


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

@dataclass
class LatexError:
    """A single error extracted from a LaTeX log file."""
    line_number: int | None   # Line in .tex source, if detected.
    message: str              # Human-readable error message.
    context: str              # Surrounding log lines for debugging.


# Patterns for common LaTeX errors.
_RE_ERROR_LINE = re.compile(
    r"^! (?P<msg>.+?)$",
    re.MULTILINE,
)
_RE_LINE_NUMBER = re.compile(
    r"^l\.(?P<lineno>\d+)\s",
    re.MULTILINE,
)
_RE_UNDEFINED_CS = re.compile(
    r"Undefined control sequence.*?\\(?P<cs>\S+)",
    re.DOTALL,
)
_RE_MISSING_PKG = re.compile(
    r"! LaTeX Error: File `(?P<pkg>[^']+)' not found",
)
_RE_MISSING_FILE = re.compile(
    r"! I can't find file `(?P<file>[^']+)'",
)
_RE_DIMENSION_TOO_LARGE = re.compile(
    r"! Dimension too large",
)
_RE_RUNAWAY_ARG = re.compile(
    r"^Runaway argument\?",
    re.MULTILINE,
)


def parse_log(log_path: Path) -> list[LatexError]:
    """
    Parse a LaTeX .log file and return structured error objects.

    This does not attempt to parse warnings -- only errors that cause
    compilation failure.
    """
    if not log_path.is_file():
        return [LatexError(
            line_number=None,
            message="Log file not found (compilation may have crashed).",
            context="",
        )]

    text = log_path.read_text(encoding="utf-8", errors="replace")
    errors: list[LatexError] = []

    for m in _RE_ERROR_LINE.finditer(text):
        msg = m.group("msg").strip()
        start = max(0, m.start() - 200)
        end = min(len(text), m.end() + 500)
        context = text[start:end]

        # Try to extract the offending line number.
        line_match = _RE_LINE_NUMBER.search(context)
        lineno = int(line_match.group("lineno")) if line_match else None

        # Enhance message for common error types.
        pkg_match = _RE_MISSING_PKG.search(m.group(0))
        if pkg_match:
            msg = (
                f"Missing package: {pkg_match.group('pkg')}.  "
                f"Install it via your TeX distribution's package manager."
            )

        # Detect dimension overflow (common with extreme TikZ params).
        if _RE_DIMENSION_TOO_LARGE.search(context):
            msg += (
                "  [Hint: a coordinate or length exceeded TeX's maximum "
                "dimension (~575cm). Check your parameter range.]"
            )

        errors.append(LatexError(
            line_number=lineno,
            message=msg,
            context=context,
        ))

    # Detect runaway arguments (often from mismatched braces).
    for m in _RE_RUNAWAY_ARG.finditer(text):
        start = max(0, m.start() - 100)
        end = min(len(text), m.end() + 400)
        errors.append(LatexError(
            line_number=None,
            message=(
                "Runaway argument detected. This usually means mismatched "
                "braces {} or brackets [] in the template."
            ),
            context=text[start:end],
        ))

    # If the log exists but we found no structured errors, the file may
    # have been truncated or the error format unrecognized.
    if not errors and "! " in text:
        errors.append(LatexError(
            line_number=None,
            message="LaTeX compilation failed (unrecognized error format).",
            context=text[-1500:],
        ))

    return errors


def format_errors(errors: list[LatexError], verbose: bool = False) -> str:
    """Format a list of LatexError objects into a readable string."""
    if not errors:
        return "No errors detected."
    parts: list[str] = []
    for i, err in enumerate(errors, 1):
        loc = f"line {err.line_number}" if err.line_number else "unknown location"
        parts.append(f"  [{i}] {err.message} ({loc})")
        if verbose and err.context:
            # Indent context lines for readability.
            for line in err.context.splitlines()[:10]:
                parts.append(f"      | {line}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Package detection utilities
# ---------------------------------------------------------------------------

# Packages that require --shell-escape.
SHELL_ESCAPE_PACKAGES = frozenset({
    "minted", "pythontex", "svg", "gnuplot-lua-tikz",
})

_RE_USEPACKAGE = re.compile(
    r"\\usepackage"
    r"(?:\s*\[(?P<options>[^\]]*)\])?"
    r"\s*\{(?P<packages>[^}]+)\}",
)

_RE_USETIKZLIBRARY = re.compile(
    r"\\usetikzlibrary\s*\{(?P<libs>[^}]+)\}",
)

_RE_PGFPLOTSSET = re.compile(
    r"\\pgfplotsset\s*\{",
)


def detect_packages(preamble: str) -> set[str]:
    """Extract all package names from a LaTeX preamble."""
    packages: set[str] = set()
    for m in _RE_USEPACKAGE.finditer(preamble):
        for pkg in m.group("packages").split(","):
            packages.add(pkg.strip())
    return packages


def detect_tikz_libraries(preamble: str) -> set[str]:
    """Extract all TikZ library names from a preamble."""
    libs: set[str] = set()
    for m in _RE_USETIKZLIBRARY.finditer(preamble):
        for lib in m.group("libs").split(","):
            libs.add(lib.strip())
    return libs


def needs_shell_escape(packages: set[str]) -> bool:
    """Return True if any detected package requires --shell-escape."""
    return bool(packages & SHELL_ESCAPE_PACKAGES)


def uses_pgfplots(preamble: str) -> bool:
    """Return True if the preamble loads pgfplots."""
    return "pgfplots" in detect_packages(preamble)
