"""
Backend auto-detection and system probing.

Discovers which PDF-to-image backends are available, selects the best
one according to the priority chain, and provides diagnostics when
nothing is found.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from tikzgif.backends import BACKEND_PRIORITY, ConversionBackend

logger = logging.getLogger(__name__)


@dataclass
class ToolProbe:
    """Result of probing a single external tool."""
    name: str
    found: bool
    path: Optional[str]
    version: Optional[str]
    notes: Optional[str] = None


def _probe_tool(name: str, version_flag: str = "--version") -> ToolProbe:
    which_path = shutil.which(name)
    if which_path is None:
        return ToolProbe(name=name, found=False, path=None, version=None)
    try:
        result = subprocess.run(
            [which_path, version_flag], capture_output=True, timeout=10,
        )
        output = (result.stdout or result.stderr).decode(errors="replace")
        first_line = output.strip().split("\n")[0].strip()
        return ToolProbe(name=name, found=True, path=which_path,
                         version=first_line or "unknown")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ToolProbe(name=name, found=True, path=which_path,
                         version=None, notes=f"Version check failed: {exc}")


def probe_system() -> Dict[str, ToolProbe]:
    """Probe system for all relevant external tools and Python libraries."""
    tools: Dict[str, ToolProbe] = {}
    tools["pdftoppm"] = _probe_tool("pdftoppm", "-v")
    tools["pdftocairo"] = _probe_tool("pdftocairo", "-v")

    for gs_name in ("gs", "gswin64c", "gswin32c"):
        probe = _probe_tool(gs_name, "--version")
        if probe.found:
            tools["ghostscript"] = probe
            break
    else:
        tools["ghostscript"] = ToolProbe(
            name="ghostscript", found=False, path=None, version=None)

    for im_name in ("magick", "convert"):
        probe = _probe_tool(im_name, "-version")
        if probe.found and probe.version and "ImageMagick" in probe.version:
            probe.notes = _check_imagemagick_policy()
            tools["imagemagick"] = probe
            break
    else:
        tools["imagemagick"] = ToolProbe(
            name="imagemagick", found=False, path=None, version=None)

    tools["pymupdf"] = _probe_python_lib("fitz", "PyMuPDF")
    tools["pdf2image"] = _probe_python_lib("pdf2image", "pdf2image")
    tools["pillow"] = _probe_python_lib("PIL", "Pillow")
    return tools


def _probe_python_lib(import_name: str, display_name: str) -> ToolProbe:
    try:
        mod = __import__(import_name)
        version = getattr(mod, "__version__", getattr(mod, "version", "unknown"))
        if callable(version):
            version = version()
        return ToolProbe(name=display_name, found=True, path=None,
                         version=str(version))
    except ImportError:
        return ToolProbe(name=display_name, found=False, path=None, version=None)


def _check_imagemagick_policy() -> Optional[str]:
    for policy_path in (Path("/etc/ImageMagick-6/policy.xml"),
                        Path("/etc/ImageMagick-7/policy.xml"),
                        Path("/usr/local/etc/ImageMagick-7/policy.xml")):
        if policy_path.is_file():
            try:
                text = policy_path.read_text(encoding="utf-8", errors="replace")
                if 'pattern="PDF"' in text and 'rights="none"' in text:
                    return (f"WARNING: {policy_path} blocks PDF conversion. "
                            f"Change PDF rights to 'read'.")
            except OSError:
                pass
    return None


def select_backend(preferred: Optional[str] = None) -> ConversionBackend:
    """Return the best available backend or raise with install hints."""
    if preferred is not None:
        for cls in BACKEND_PRIORITY:
            if cls.name == preferred:
                if cls.is_available():
                    logger.info("Using preferred backend: %s", cls.name)
                    return cls()
                logger.warning("Preferred backend '%s' not available.", preferred)
                break

    for cls in BACKEND_PRIORITY:
        if cls.is_available():
            logger.info("Auto-selected backend: %s", cls.name)
            return cls()

    _raise_no_backend_error()


def _raise_no_backend_error() -> None:
    os_name = platform.system()
    lines = ["No PDF-to-image backend is available.", "",
             "Install at least one of the following:", ""]
    if os_name == "Darwin":
        lines += ["  Option A (recommended):  brew install poppler",
                   "  Option B:                pip install PyMuPDF",
                   "  Option C:                brew install ghostscript",
                   "  Option D:                brew install imagemagick"]
    elif os_name == "Linux":
        lines += ["  Option A (recommended):  sudo apt-get install poppler-utils",
                   "  Option B:                pip install PyMuPDF",
                   "  Option C:                sudo apt-get install ghostscript",
                   "  Option D:                sudo apt-get install imagemagick"]
    elif os_name == "Windows":
        lines += ["  Option A (recommended):  choco install poppler",
                   "  Option B:                pip install PyMuPDF",
                   "  Option C:                choco install ghostscript",
                   "  Option D:                choco install imagemagick"]
    else:
        lines.append("  Install poppler-utils, PyMuPDF, Ghostscript, or ImageMagick.")
    lines += ["", "For fastest results, install poppler-utils (provides pdftoppm)."]
    raise RuntimeError("\n".join(lines))


def print_diagnostics() -> str:
    """Return a human-readable diagnostics report."""
    probes = probe_system()
    lines = ["tikzgif backend diagnostics", "=" * 40,
             f"Platform: {platform.system()} {platform.release()}",
             f"Python:   {platform.python_version()}", "",
             "External tools:"]
    for name in ("pdftoppm", "pdftocairo", "ghostscript", "imagemagick"):
        p = probes.get(name)
        if p is None:
            continue
        status = "FOUND" if p.found else "NOT FOUND"
        ver = f"  ({p.version})" if p.version else ""
        path = f"  [{p.path}]" if p.path else ""
        lines.append(f"  {name:20s} {status}{ver}{path}")
        if p.notes:
            lines.append(f"    {p.notes}")
    lines += ["", "Python libraries:"]
    for name in ("pymupdf", "pdf2image", "pillow"):
        p = probes.get(name)
        if p is None:
            continue
        status = "FOUND" if p.found else "NOT FOUND"
        ver = f"  ({p.version})" if p.version else ""
        lines.append(f"  {name:20s} {status}{ver}")
    lines.append("")
    try:
        backend = select_backend()
        lines.append(f"Selected backend: {backend.name}")
    except RuntimeError:
        lines.append("Selected backend: NONE (see install instructions above)")
    return "\n".join(lines)
