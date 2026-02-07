"""
PDF-to-image conversion backends.

Each backend converts a multi-page PDF into a sequence of PIL Image objects.
The module probes the system for available tools and exposes a unified
interface regardless of which backend is active.

Backend priority (highest to lowest):
    1. pdftoppm   -- fastest, highest quality, from poppler-utils
    2. PyMuPDF    -- pure-Python, no subprocess overhead
    3. pdf2image  -- Python wrapper around poppler (same quality as #1)
    4. Ghostscript -- most portable, needed by ImageMagick anyway
    5. ImageMagick -- most common but has security-policy issues

All backends produce List[PIL.Image.Image] in RGBA mode.
"""

from __future__ import annotations

import abc
import logging
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class ColorSpace(Enum):
    """Target color space for rendered frames."""
    RGB = auto()
    RGBA = auto()
    GRAYSCALE = auto()


@dataclass(frozen=True)
class RenderConfig:
    """Immutable rendering parameters shared by every backend.

    DPI guide
    ---------
    ======  ============================  ============================
    DPI     Pixel size (US Letter)        Typical use
    ======  ============================  ============================
    72      612 x 792                     Screen preview
    150     1275 x 1650                   Web / GIF quality
    300     2550 x 3300                   Presentation quality
    600     5100 x 6600                   Print quality
    1200    10200 x 13200                 Archival (rarely needed)
    ======  ============================  ============================
    """
    dpi: int = 300
    color_space: ColorSpace = ColorSpace.RGBA
    background: Optional[str] = "white"      # None = transparent
    antialias: bool = True
    antialias_factor: int = 2                # supersampling multiplier
    threads: int = 4

    @property
    def render_dpi(self) -> int:
        """Effective DPI when anti-aliasing via super-sampling."""
        if self.antialias and self.antialias_factor > 1:
            return self.dpi * self.antialias_factor
        return self.dpi

    def pixel_dimensions(self, width_pt: float, height_pt: float) -> Tuple[int, int]:
        """Convert point dimensions to pixel dimensions at target DPI."""
        px_w = int(round(width_pt * self.dpi / 72.0))
        px_h = int(round(height_pt * self.dpi / 72.0))
        return (px_w, px_h)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ConversionBackend(abc.ABC):
    """Abstract interface that every backend must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    def convert(
        self,
        pdf_path: Path,
        config: RenderConfig,
        pages: Optional[Sequence[int]] = None,
    ) -> List[Image.Image]:
        """Convert *pdf_path* into a list of PIL Images (one per page)."""

    @staticmethod
    @abc.abstractmethod
    def is_available() -> bool:
        """Return True if this backend's dependencies are satisfied."""

    @staticmethod
    @abc.abstractmethod
    def install_hint() -> str:
        """Human-readable install instructions for the current platform."""

    @staticmethod
    def _ensure_rgba(img: Image.Image, background: Optional[str]) -> Image.Image:
        """Normalise any PIL image to RGBA, compositing onto *background*."""
        if img.mode == "RGBA":
            if background is not None:
                bg = Image.new("RGBA", img.size, background)
                bg.paste(img, mask=img)
                return bg
            return img
        if img.mode in ("RGB", "L", "P"):
            return img.convert("RGBA")
        return img.convert("RGBA")

    @staticmethod
    def _downscale_aa(
        img: Image.Image, target_dpi: int, render_dpi: int
    ) -> Image.Image:
        """Downscale a super-sampled image back to *target_dpi*."""
        if render_dpi <= target_dpi:
            return img
        scale = target_dpi / render_dpi
        new_size = (int(round(img.width * scale)), int(round(img.height * scale)))
        return img.resize(new_size, Image.LANCZOS)


# ---------------------------------------------------------------------------
# 1. pdftoppm (poppler-utils)
# ---------------------------------------------------------------------------

class PdftoppmBackend(ConversionBackend):
    """Fastest backend -- ~15 ms/frame at 300 DPI, ~50 ms at 600 DPI.

    Command flags
    -------------
    -png              Output PNG (lossless, supports alpha after composite)
    -r <dpi>          Resolution
    -aaVector yes/no  Path anti-aliasing (FreeType/cairo)
    -aaText yes/no    Text anti-aliasing
    -gray             Force grayscale output
    -f <n> -l <n>     First/last page (1-based)
    -nthreads <n>     Parallel rendering threads (poppler >= 21.03)
    """

    name = "pdftoppm"

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pdftoppm") is not None

    @staticmethod
    def install_hint() -> str:
        os_name = platform.system()
        if os_name == "Darwin":
            return "brew install poppler"
        if os_name == "Linux":
            return "sudo apt-get install poppler-utils"
        if os_name == "Windows":
            return "choco install poppler"
        return "Install poppler-utils for your platform."

    def convert(self, pdf_path, config, pages=None):
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(pdf_path)

        results: List[Image.Image] = []

        with tempfile.TemporaryDirectory(prefix="tikzgif_pdftoppm_") as tmpdir:
            prefix = Path(tmpdir) / "frame"
            cmd: List[str] = ["pdftoppm", "-png"]

            effective_dpi = config.render_dpi if (
                config.antialias and config.antialias_factor > 1
            ) else config.dpi
            cmd += ["-r", str(effective_dpi)]

            if config.antialias:
                cmd += ["-aa", "yes"]

            if config.color_space == ColorSpace.GRAYSCALE:
                cmd += ["-gray"]

            if pages is not None and len(pages) > 0:
                cmd += ["-f", str(min(pages) + 1), "-l", str(max(pages) + 1)]

            if config.threads > 1:
                cmd += ["-nthreads", str(config.threads)]

            cmd += [str(pdf_path), str(prefix)]
            logger.debug("pdftoppm command: %s", " ".join(cmd))

            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"pdftoppm failed (rc={proc.returncode}):\n"
                    f"{proc.stderr.decode(errors='replace')}"
                )

            png_files = sorted(Path(tmpdir).glob("frame-*.png"))
            if not png_files:
                raise RuntimeError("pdftoppm produced no output files.")

            requested_set = set(pages) if pages is not None else None

            for png_file in png_files:
                page_num_str = png_file.stem.split("-")[-1]
                page_idx = int(page_num_str) - 1
                if requested_set is not None and page_idx not in requested_set:
                    continue
                img = Image.open(png_file)
                img.load()
                img = self._ensure_rgba(img, config.background)
                if config.antialias and config.antialias_factor > 1:
                    img = self._downscale_aa(img, config.dpi, effective_dpi)
                results.append(img)

        return results


# ---------------------------------------------------------------------------
# 2. PyMuPDF (fitz)
# ---------------------------------------------------------------------------

class PyMuPDFBackend(ConversionBackend):
    """Pure-Python via MuPDF. ~20 ms/frame at 300 DPI, ~70 ms at 600 DPI.

    No subprocess calls. Renders at arbitrary DPI via a transformation
    matrix. Native anti-aliasing. Supports transparent backgrounds.
    """

    name = "pymupdf"

    @staticmethod
    def is_available() -> bool:
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def install_hint() -> str:
        return "pip install PyMuPDF"

    def convert(self, pdf_path, config, pages=None):
        import fitz
        pdf_path = pdf_path.resolve()
        doc = fitz.open(str(pdf_path))

        page_indices = sorted(pages) if pages is not None else list(range(len(doc)))
        scale = config.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        results: List[Image.Image] = []

        for page_idx in page_indices:
            if page_idx < 0 or page_idx >= len(doc):
                continue
            page = doc.load_page(page_idx)
            alpha = config.color_space == ColorSpace.RGBA and config.background is None
            pix = page.get_pixmap(matrix=matrix, alpha=alpha)

            mode = "RGBA" if alpha else "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            img = self._ensure_rgba(img, config.background)
            if config.color_space == ColorSpace.GRAYSCALE:
                img = img.convert("L").convert("RGBA")
            results.append(img)

        doc.close()
        return results


# ---------------------------------------------------------------------------
# 3. pdf2image (Python wrapper around poppler)
# ---------------------------------------------------------------------------

class Pdf2ImageBackend(ConversionBackend):
    """Wraps pdf2image library. Same quality as pdftoppm, ~25 ms/frame."""

    name = "pdf2image"

    @staticmethod
    def is_available() -> bool:
        try:
            import pdf2image  # noqa: F401
            return shutil.which("pdftoppm") is not None
        except ImportError:
            return False

    @staticmethod
    def install_hint() -> str:
        os_name = platform.system()
        base = "pip install pdf2image"
        if os_name == "Darwin":
            return f"{base} && brew install poppler"
        if os_name == "Linux":
            return f"{base} && sudo apt-get install poppler-utils"
        if os_name == "Windows":
            return f"{base}  (also: choco install poppler)"
        return base

    def convert(self, pdf_path, config, pages=None):
        from pdf2image import convert_from_path
        pdf_path = pdf_path.resolve()

        effective_dpi = config.render_dpi if (
            config.antialias and config.antialias_factor > 1
        ) else config.dpi

        kwargs: Dict = {
            "pdf_path": str(pdf_path),
            "dpi": effective_dpi,
            "fmt": "png",
            "thread_count": config.threads,
        }
        if pages is not None and len(pages) > 0:
            kwargs["first_page"] = min(pages) + 1
            kwargs["last_page"] = max(pages) + 1
        if config.color_space == ColorSpace.GRAYSCALE:
            kwargs["grayscale"] = True
        if config.background is None:
            kwargs["transparent"] = True

        pil_images = convert_from_path(**kwargs)
        results: List[Image.Image] = []
        requested_set = set(pages) if pages is not None else None
        base_idx = min(pages) if pages else 0

        for i, img in enumerate(pil_images):
            page_idx = base_idx + i
            if requested_set is not None and page_idx not in requested_set:
                continue
            img = self._ensure_rgba(img, config.background)
            if config.antialias and config.antialias_factor > 1:
                img = self._downscale_aa(img, config.dpi, effective_dpi)
            results.append(img)

        return results


# ---------------------------------------------------------------------------
# 4. Ghostscript
# ---------------------------------------------------------------------------

class GhostscriptBackend(ConversionBackend):
    """Most portable. ~40 ms/frame at 300 DPI, ~150 ms at 600 DPI.

    Command flags
    -------------
    -sDEVICE=pngalpha       32-bit RGBA (transparent background)
    -sDEVICE=png16m          24-bit RGB (opaque)
    -sDEVICE=pnggray         8-bit grayscale
    -r<dpi>                  Resolution
    -dTextAlphaBits=4        Text AA (1=none, 2=low, 4=full)
    -dGraphicsAlphaBits=4    Vector AA
    -dFirstPage/-dLastPage   Page range (1-based)
    -dNumRenderingThreads=N  Parallel rendering (GS >= 9.54)
    """

    name = "ghostscript"

    @staticmethod
    def _gs_executable() -> Optional[str]:
        for name in ("gs", "gswin64c", "gswin32c"):
            if shutil.which(name) is not None:
                return name
        return None

    @staticmethod
    def is_available() -> bool:
        return GhostscriptBackend._gs_executable() is not None

    @staticmethod
    def install_hint() -> str:
        os_name = platform.system()
        if os_name == "Darwin":
            return "brew install ghostscript"
        if os_name == "Linux":
            return "sudo apt-get install ghostscript"
        if os_name == "Windows":
            return "choco install ghostscript"
        return "Install Ghostscript for your platform."

    def convert(self, pdf_path, config, pages=None):
        gs_bin = self._gs_executable()
        if gs_bin is None:
            raise RuntimeError("Ghostscript not found on PATH.")
        pdf_path = pdf_path.resolve()

        effective_dpi = config.render_dpi if (
            config.antialias and config.antialias_factor > 1
        ) else config.dpi

        with tempfile.TemporaryDirectory(prefix="tikzgif_gs_") as tmpdir:
            out_pattern = str(Path(tmpdir) / "frame-%04d.png")

            if config.background is None:
                device = "pngalpha"
            elif config.color_space == ColorSpace.GRAYSCALE:
                device = "pnggray"
            else:
                device = "png16m"

            cmd: List[str] = [
                gs_bin, "-dBATCH", "-dNOPAUSE", "-dSAFER", "-dQUIET",
                f"-sDEVICE={device}", f"-r{effective_dpi}",
                f"-sOutputFile={out_pattern}",
            ]

            if config.antialias:
                cmd += ["-dTextAlphaBits=4", "-dGraphicsAlphaBits=4"]
            else:
                cmd += ["-dTextAlphaBits=1", "-dGraphicsAlphaBits=1"]

            if pages is not None and len(pages) > 0:
                cmd += [f"-dFirstPage={min(pages)+1}", f"-dLastPage={max(pages)+1}"]

            if config.threads > 1:
                cmd += [f"-dNumRenderingThreads={config.threads}"]

            cmd.append(str(pdf_path))
            logger.debug("Ghostscript command: %s", " ".join(cmd))

            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Ghostscript failed (rc={proc.returncode}):\n"
                    f"{proc.stderr.decode(errors='replace')}"
                )

            png_files = sorted(Path(tmpdir).glob("frame-*.png"))
            if not png_files:
                raise RuntimeError("Ghostscript produced no output files.")

            results: List[Image.Image] = []
            requested_set = set(pages) if pages is not None else None
            base_page = min(pages) if pages else 0

            for i, png_file in enumerate(png_files):
                page_idx = base_page + i
                if requested_set is not None and page_idx not in requested_set:
                    continue
                img = Image.open(png_file)
                img.load()
                img = self._ensure_rgba(img, config.background)
                if config.antialias and config.antialias_factor > 1:
                    img = self._downscale_aa(img, config.dpi, effective_dpi)
                results.append(img)

        return results


# ---------------------------------------------------------------------------
# 5. ImageMagick
# ---------------------------------------------------------------------------

class ImageMagickBackend(ConversionBackend):
    """Wrapper. ~50 ms/frame at 300 DPI. Uses Ghostscript internally.

    SECURITY NOTE: ImageMagick policy.xml may block PDF conversion.
    Edit /etc/ImageMagick-*/policy.xml:
        <policy domain="coder" rights="read" pattern="PDF" />
    """

    name = "imagemagick"

    @staticmethod
    def _magick_executable() -> Optional[str]:
        if shutil.which("magick") is not None:
            return "magick"
        if shutil.which("convert") is not None:
            return "convert"
        return None

    @staticmethod
    def is_available() -> bool:
        exe = ImageMagickBackend._magick_executable()
        if exe is None:
            return False
        try:
            result = subprocess.run(
                [exe, "-version"], capture_output=True, timeout=10,
            )
            return b"ImageMagick" in result.stdout
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def install_hint() -> str:
        os_name = platform.system()
        if os_name == "Darwin":
            hint = "brew install imagemagick"
        elif os_name == "Linux":
            hint = "sudo apt-get install imagemagick"
        elif os_name == "Windows":
            hint = "choco install imagemagick"
        else:
            hint = "Install ImageMagick for your platform."
        hint += (
            "\n\nIf PDF conversion is blocked by policy, edit "
            "/etc/ImageMagick-*/policy.xml and set:\n"
            '  <policy domain="coder" rights="read" pattern="PDF" />'
        )
        return hint

    def convert(self, pdf_path, config, pages=None):
        exe = self._magick_executable()
        if exe is None:
            raise RuntimeError("ImageMagick not found on PATH.")
        pdf_path = pdf_path.resolve()

        effective_dpi = config.render_dpi if (
            config.antialias and config.antialias_factor > 1
        ) else config.dpi

        with tempfile.TemporaryDirectory(prefix="tikzgif_magick_") as tmpdir:
            out_pattern = str(Path(tmpdir) / "frame.png")
            cmd: List[str] = [exe, "-density", str(effective_dpi)]
            if not config.antialias:
                cmd.append("+antialias")
            if config.background is None:
                cmd += ["-background", "none", "-alpha", "on"]
            else:
                cmd += ["-background", config.background, "-alpha", "remove"]

            if pages is not None and len(pages) > 0:
                cmd.append(f"{pdf_path}[{min(pages)}-{max(pages)}]")
            else:
                cmd.append(str(pdf_path))

            if config.color_space == ColorSpace.GRAYSCALE:
                cmd += ["-colorspace", "Gray"]
            cmd.append(out_pattern)
            logger.debug("ImageMagick command: %s", " ".join(cmd))

            proc = subprocess.run(cmd, capture_output=True, timeout=300)
            if proc.returncode != 0:
                stderr_text = proc.stderr.decode(errors="replace")
                if "not authorized" in stderr_text.lower():
                    raise RuntimeError(
                        "ImageMagick PDF conversion blocked by security policy.\n"
                        "Edit /etc/ImageMagick-*/policy.xml to allow PDF reads:\n"
                        '  <policy domain="coder" rights="read" pattern="PDF" />'
                    )
                raise RuntimeError(
                    f"ImageMagick failed (rc={proc.returncode}):\n{stderr_text}"
                )

            png_files = sorted(Path(tmpdir).glob("frame*.png"))
            if not png_files:
                raise RuntimeError("ImageMagick produced no output files.")

            results: List[Image.Image] = []
            requested_set = set(pages) if pages is not None else None
            base_page = min(pages) if pages else 0

            for i, png_file in enumerate(png_files):
                page_idx = base_page + i
                if requested_set is not None and page_idx not in requested_set:
                    continue
                img = Image.open(png_file)
                img.load()
                img = self._ensure_rgba(img, config.background)
                if config.antialias and config.antialias_factor > 1:
                    img = self._downscale_aa(img, config.dpi, effective_dpi)
                results.append(img)

        return results


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

BACKEND_PRIORITY: List[type] = [
    PdftoppmBackend,
    PyMuPDFBackend,
    Pdf2ImageBackend,
    GhostscriptBackend,
    ImageMagickBackend,
]

_BACKEND_BY_NAME: Dict[str, type] = {cls.name: cls for cls in BACKEND_PRIORITY}


def get_backend_by_name(name: str) -> ConversionBackend:
    """Instantiate a backend by its short name."""
    cls = _BACKEND_BY_NAME.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown backend '{name}'. "
            f"Available: {list(_BACKEND_BY_NAME.keys())}"
        )
    if not cls.is_available():
        raise RuntimeError(
            f"Backend '{name}' is not available on this system.\n"
            f"Install: {cls.install_hint()}"
        )
    return cls()
