"""LaTeX engine detection, selection, and error parsing."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from tikzgif.exceptions import LatexNotFoundError
from tikzgif.types import LatexEngine


def detect_available_engines() -> dict[LatexEngine, Path | None]:
    """Probe ``$PATH`` for installed LaTeX engines.

    Returns:
        Mapping from each ``LatexEngine`` member to its resolved path,
        or ``None`` if that engine is not installed.
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
    """Select the best available LaTeX engine.

    Selection priority:
        1. User's explicit *preferred* engine (if installed).
        2. Package-driven: ``fontspec``/``unicode-math`` require XeLaTeX
           or LuaLaTeX; ``luacode``/``luatexbase`` require LuaLaTeX.
        3. Default: ``pdflatex`` (fastest for most TikZ work).

    Args:
        preferred: Explicitly requested engine, or ``None`` for auto.
        packages: Set of LaTeX package names detected in the preamble.

    Returns:
        The selected ``LatexEngine``.

    Raises:
        LatexNotFoundError: If no suitable engine is installed.
    """
    available = detect_available_engines()
    packages = packages or set()

    unicode_packages = {"fontspec", "unicode-math", "luacode", "luatexbase"}
    needs_unicode = bool(packages & unicode_packages)

    lua_only = {"luacode", "luatexbase", "tikz-feynman"}
    needs_lua = bool(packages & lua_only)

    if preferred is not None:
        if available.get(preferred) is not None:
            return preferred

    if needs_lua:
        if available.get(LatexEngine.LUALATEX):
            return LatexEngine.LUALATEX
        raise LatexNotFoundError(
            f"LuaLaTeX is required by detected packages "
            f"({packages & lua_only}) but is not installed.",
            engine="lualatex",
        )

    if needs_unicode:
        for eng in (LatexEngine.XELATEX, LatexEngine.LUALATEX):
            if available.get(eng):
                return eng
        raise LatexNotFoundError(
            f"XeLaTeX or LuaLaTeX is required by detected packages "
            f"({packages & unicode_packages}) but neither is installed.",
            engine="xelatex",
        )

    if available.get(LatexEngine.PDFLATEX):
        return LatexEngine.PDFLATEX

    for eng, path in available.items():
        if path is not None:
            return eng

    raise LatexNotFoundError(
        "No LaTeX engine found on PATH. Install TeX Live or MiKTeX."
    )


def build_compile_command(
    engine: LatexEngine,
    tex_path: Path,
    output_dir: Path,
    shell_escape: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the shell command to compile a single ``.tex`` file.

    Each invocation runs in ``nonstopmode`` with ``-halt-on-error`` and
    writes output to *output_dir* for process-isolated parallel builds.

    Args:
        engine: LaTeX engine to invoke.
        tex_path: Path to the ``.tex`` source file.
        output_dir: Directory for ``.pdf``, ``.aux``, and ``.log`` output.
        shell_escape: Whether to pass ``--shell-escape``.
        extra_args: Additional arguments forwarded to the engine.

    Returns:
        Command list suitable for ``subprocess.run()``.
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


@dataclass
class LatexError:
    """A single error extracted from a LaTeX ``.log`` file.

    Attributes:
        line_number: Line in ``.tex`` source where the error occurred.
        message: Human-readable error description.
        context: Surrounding log lines for debugging.
    """

    line_number: int | None
    message: str
    context: str


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
    """Parse a LaTeX ``.log`` file and return structured error objects.

    Only errors that cause compilation failure are extracted; warnings
    are ignored.

    Args:
        log_path: Path to the ``.log`` file produced by the LaTeX engine.

    Returns:
        List of ``LatexError`` objects, possibly empty if no errors found.
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

        line_match = _RE_LINE_NUMBER.search(context)
        lineno = int(line_match.group("lineno")) if line_match else None

        pkg_match = _RE_MISSING_PKG.search(m.group(0))
        if pkg_match:
            msg = (
                f"Missing package: {pkg_match.group('pkg')}.  "
                f"Install it via your TeX distribution's package manager."
            )

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

    if not errors and "! " in text:
        errors.append(LatexError(
            line_number=None,
            message="LaTeX compilation failed (unrecognized error format).",
            context=text[-1500:],
        ))

    return errors


def format_errors(errors: list[LatexError], verbose: bool = False) -> str:
    """Format a list of ``LatexError`` objects into a readable string.

    Args:
        errors: Parsed errors from ``parse_log()``.
        verbose: If ``True``, include surrounding log context lines.

    Returns:
        Multi-line string summarizing all errors.
    """
    if not errors:
        return "No errors detected."
    parts: list[str] = []
    for i, err in enumerate(errors, 1):
        loc = f"line {err.line_number}" if err.line_number else "unknown location"
        parts.append(f"  [{i}] {err.message} ({loc})")
        if verbose and err.context:
            for line in err.context.splitlines()[:10]:
                parts.append(f"      | {line}")
    return "\n".join(parts)


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
    """Extract all ``\\usepackage`` names from a LaTeX preamble.

    Args:
        preamble: LaTeX source text before ``\\begin{document}``.

    Returns:
        Set of package name strings.
    """
    packages: set[str] = set()
    for m in _RE_USEPACKAGE.finditer(preamble):
        for pkg in m.group("packages").split(","):
            packages.add(pkg.strip())
    return packages


def detect_tikz_libraries(preamble: str) -> set[str]:
    """Extract all ``\\usetikzlibrary`` names from a LaTeX preamble.

    Args:
        preamble: LaTeX source text before ``\\begin{document}``.

    Returns:
        Set of TikZ library name strings.
    """
    libs: set[str] = set()
    for m in _RE_USETIKZLIBRARY.finditer(preamble):
        for lib in m.group("libs").split(","):
            libs.add(lib.strip())
    return libs


def needs_shell_escape(packages: set[str]) -> bool:
    """Return ``True`` if any package in *packages* requires ``--shell-escape``."""
    return bool(packages & SHELL_ESCAPE_PACKAGES)


def uses_pgfplots(preamble: str) -> bool:
    """Return ``True`` if *preamble* loads the ``pgfplots`` package."""
    return "pgfplots" in detect_packages(preamble)
