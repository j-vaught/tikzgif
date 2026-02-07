"""
Runtime configuration and system-dependency discovery.

This module locates external tools (pdflatex, pdftoppm, gs) on the system
and exposes resolved paths for use by the compiler and converter modules.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from tikzgif.engine import detect_available_engines, select_engine
from tikzgif.exceptions import ConverterNotFoundError, LatexNotFoundError
from tikzgif.types import LatexEngine


@dataclass(frozen=True)
class ResolvedPaths:
    """Absolute paths to external binaries resolved at startup."""

    latex_engine: Path
    converter: Path          # pdftoppm or gs
    converter_name: str      # "pdftoppm" or "gs"


def resolve_latex_engine(engine: LatexEngine) -> Path:
    """Find the absolute path to the requested LaTeX engine."""
    path = shutil.which(engine.value)
    if path is None:
        raise LatexNotFoundError(
            f"{engine.value!r} not found on $PATH. "
            f"Install a TeX distribution (TeX Live, MiKTeX)."
        )
    return Path(path)


def resolve_converter() -> tuple[Path, str]:
    """Find a PDF-to-PNG converter, preferring pdftoppm over ghostscript."""
    for name in ("pdftoppm", "gs"):
        path = shutil.which(name)
        if path is not None:
            return Path(path), name
    raise ConverterNotFoundError(
        "No PDF-to-PNG converter found. "
        "Install poppler-utils (pdftoppm) or ghostscript (gs)."
    )


def resolve_all(engine: LatexEngine) -> ResolvedPaths:
    """Resolve all external dependencies at once."""
    latex_path = resolve_latex_engine(engine)
    converter_path, converter_name = resolve_converter()
    return ResolvedPaths(
        latex_engine=latex_path,
        converter=converter_path,
        converter_name=converter_name,
    )
