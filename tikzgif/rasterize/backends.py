"""PDF-to-image conversion backends.

Each backend converts a PDF into a sequence of PIL ``Image`` objects.
The module probes the system for available tools and exposes a unified
interface regardless of which backend is active.

Backend priority (highest to lowest): pdftoppm, PyMuPDF, pdf2image,
Ghostscript, ImageMagick.  All backends produce ``RGBA`` PIL images.
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

from PIL import Image

from tikzgif.exceptions import ConverterError, ConverterNotFoundError

logger = logging.getLogger(__name__)


class ColorSpace(Enum):
    """Target color space for rendered frames."""

    RGB = auto()
    RGBA = auto()
    GRAYSCALE = auto()


@dataclass(frozen=True)
class RenderConfig:
    """Immutable rendering parameters shared by every backend.

    Attributes:
        dpi: Target resolution in dots per inch.
        color_space: Output color space.
        background: Background color name, or ``None`` for transparency.
        antialias: Whether to enable anti-aliasing via supersampling.
        antialias_factor: Supersampling multiplier when *antialias* is ``True``.
        threads: Number of rendering threads (backend-dependent support).
    """

    dpi: int = 300
    color_space: ColorSpace = ColorSpace.RGBA
    background: str | None = "white"
    antialias: bool = True
    antialias_factor: int = 2
    threads: int = 4

    @property
    def render_dpi(self) -> int:
        """Effective DPI when anti-aliasing via supersampling."""
        if self.antialias and self.antialias_factor > 1:
            return self.dpi * self.antialias_factor
        return self.dpi

    def pixel_dimensions(self, width_pt: float, height_pt: float) -> tuple[int, int]:
        """Convert point dimensions to pixel dimensions at target DPI."""
        px_w = int(round(width_pt * self.dpi / 72.0))
        px_h = int(round(height_pt * self.dpi / 72.0))
        return (px_w, px_h)


class ConversionBackend(abc.ABC):
    """Abstract interface that every rasterization backend must implement."""

    name: str = "abstract"

    @abc.abstractmethod
    def convert(
        self,
        pdf_path: Path,
        config: RenderConfig,
        pages: list[int] | None = None,
    ) -> list[Image.Image]:
        """Convert *pdf_path* into a list of PIL Images (one per page).

        Args:
            pdf_path: Path to the input PDF file.
            config: Rendering parameters.
            pages: Zero-based page indices to convert, or ``None`` for all.

        Returns:
            List of RGBA PIL Images.

        Raises:
            ConverterError: If the conversion subprocess fails.
            FileNotFoundError: If *pdf_path* does not exist.
        """

    @staticmethod
    @abc.abstractmethod
    def is_available() -> bool:
        """Return ``True`` if this backend's dependencies are satisfied."""

    @staticmethod
    @abc.abstractmethod
    def install_hint() -> str:
        """Return platform-specific installation instructions."""

    @staticmethod
    def _ensure_rgba(img: Image.Image, background: str | None) -> Image.Image:
        """Normalize any PIL image to RGBA, compositing onto *background*."""
        if img.mode == "RGBA":
            if background is not None:
                bg = Image.new("RGBA", img.size, background)
                bg.paste(img, mask=img)
                return bg
            return img
        return img.convert("RGBA")

    @staticmethod
    def _downscale_aa(
        img: Image.Image, target_dpi: int, render_dpi: int
    ) -> Image.Image:
        """Downscale a supersampled image back to *target_dpi*."""
        if render_dpi <= target_dpi:
            return img
        scale = target_dpi / render_dpi
        new_size = (int(round(img.width * scale)), int(round(img.height * scale)))
        return img.resize(new_size, Image.LANCZOS)


class PdftoppmBackend(ConversionBackend):
    """Fastest backend using ``pdftoppm`` from poppler-utils."""

    name = "pdftoppm"

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if ``pdftoppm`` is on ``$PATH``."""
        return shutil.which("pdftoppm") is not None

    @staticmethod
    def install_hint() -> str:
        """Return platform-specific install instructions for poppler."""
        os_name = platform.system()
        if os_name == "Darwin":
            return "brew install poppler"
        if os_name == "Linux":
            return "sudo apt-get install poppler-utils"
        if os_name == "Windows":
            return "choco install poppler"
        return "Install poppler-utils for your platform."

    def convert(self, pdf_path, config, pages=None):
        """Convert PDF pages to RGBA images via ``pdftoppm``."""
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        results: list[Image.Image] = []

        with tempfile.TemporaryDirectory(prefix="tikzgif_pdftoppm_") as tmpdir:
            prefix = Path(tmpdir) / "frame"
            cmd: list[str] = ["pdftoppm", "-png"]

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

            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired as exc:
                raise ConverterError(
                    "pdftoppm timed out after 300s.",
                    backend="pdftoppm",
                ) from exc

            if proc.returncode != 0:
                stderr_text = proc.stderr.decode(errors="replace")
                raise ConverterError(
                    f"pdftoppm failed (rc={proc.returncode}):\n{stderr_text}",
                    backend="pdftoppm",
                    stderr_output=stderr_text,
                )

            png_files = sorted(Path(tmpdir).glob("frame-*.png"))
            if not png_files:
                raise ConverterError(
                    "pdftoppm produced no output files.",
                    backend="pdftoppm",
                )

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


class PyMuPDFBackend(ConversionBackend):
    """Pure-Python backend via the PyMuPDF (``fitz``) library."""

    name = "pymupdf"

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if PyMuPDF is importable."""
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def install_hint() -> str:
        """Return pip install instruction for PyMuPDF."""
        return "pip install PyMuPDF"

    def convert(self, pdf_path, config, pages=None):
        """Convert PDF pages to RGBA images via PyMuPDF."""
        import fitz

        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        try:
            doc = fitz.open(str(pdf_path))
        except Exception as exc:
            raise ConverterError(
                f"PyMuPDF failed to open {pdf_path}: {exc}",
                backend="pymupdf",
            ) from exc

        page_indices = sorted(pages) if pages is not None else list(range(len(doc)))
        scale = config.dpi / 72.0
        matrix = fitz.Matrix(scale, scale)
        results: list[Image.Image] = []

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


class Pdf2ImageBackend(ConversionBackend):
    """Backend wrapping the ``pdf2image`` library (uses poppler internally)."""

    name = "pdf2image"

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if ``pdf2image`` is importable and ``pdftoppm`` is on PATH."""
        try:
            import pdf2image  # noqa: F401
            return shutil.which("pdftoppm") is not None
        except ImportError:
            return False

    @staticmethod
    def install_hint() -> str:
        """Return install instructions for pdf2image and poppler."""
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
        """Convert PDF pages to RGBA images via ``pdf2image``."""
        from pdf2image import convert_from_path

        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        effective_dpi = config.render_dpi if (
            config.antialias and config.antialias_factor > 1
        ) else config.dpi

        kwargs: dict = {
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

        try:
            pil_images = convert_from_path(**kwargs)
        except Exception as exc:
            raise ConverterError(
                f"pdf2image conversion failed: {exc}",
                backend="pdf2image",
            ) from exc

        results: list[Image.Image] = []
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


class GhostscriptBackend(ConversionBackend):
    """Backend using Ghostscript for PDF rasterization."""

    name = "ghostscript"

    @staticmethod
    def _gs_executable() -> str | None:
        """Return the Ghostscript binary name, or ``None`` if not found."""
        for name in ("gs", "gswin64c", "gswin32c"):
            if shutil.which(name) is not None:
                return name
        return None

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if Ghostscript is on ``$PATH``."""
        return GhostscriptBackend._gs_executable() is not None

    @staticmethod
    def install_hint() -> str:
        """Return platform-specific install instructions for Ghostscript."""
        os_name = platform.system()
        if os_name == "Darwin":
            return "brew install ghostscript"
        if os_name == "Linux":
            return "sudo apt-get install ghostscript"
        if os_name == "Windows":
            return "choco install ghostscript"
        return "Install Ghostscript for your platform."

    def convert(self, pdf_path, config, pages=None):
        """Convert PDF pages to RGBA images via Ghostscript."""
        gs_bin = self._gs_executable()
        if gs_bin is None:
            raise ConverterNotFoundError(
                "Ghostscript not found on PATH.",
                backend="ghostscript",
                install_hint=self.install_hint(),
            )
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

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

            cmd: list[str] = [
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

            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired as exc:
                raise ConverterError(
                    "Ghostscript timed out after 300s.",
                    backend="ghostscript",
                ) from exc

            if proc.returncode != 0:
                stderr_text = proc.stderr.decode(errors="replace")
                raise ConverterError(
                    f"Ghostscript failed (rc={proc.returncode}):\n{stderr_text}",
                    backend="ghostscript",
                    stderr_output=stderr_text,
                )

            png_files = sorted(Path(tmpdir).glob("frame-*.png"))
            if not png_files:
                raise ConverterError(
                    "Ghostscript produced no output files.",
                    backend="ghostscript",
                )

            results: list[Image.Image] = []
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


class ImageMagickBackend(ConversionBackend):
    """Backend wrapping ImageMagick ``convert``/``magick``."""

    name = "imagemagick"

    @staticmethod
    def _magick_executable() -> str | None:
        """Return the ImageMagick binary name, or ``None`` if not found."""
        if shutil.which("magick") is not None:
            return "magick"
        if shutil.which("convert") is not None:
            return "convert"
        return None

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if ImageMagick is on ``$PATH`` and functional."""
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
        """Return platform-specific install instructions for ImageMagick."""
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
        """Convert PDF pages to RGBA images via ImageMagick."""
        exe = self._magick_executable()
        if exe is None:
            raise ConverterNotFoundError(
                "ImageMagick not found on PATH.",
                backend="imagemagick",
                install_hint=self.install_hint(),
            )
        pdf_path = pdf_path.resolve()
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        effective_dpi = config.render_dpi if (
            config.antialias and config.antialias_factor > 1
        ) else config.dpi

        with tempfile.TemporaryDirectory(prefix="tikzgif_magick_") as tmpdir:
            out_pattern = str(Path(tmpdir) / "frame.png")
            cmd: list[str] = [exe, "-density", str(effective_dpi)]
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

            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired as exc:
                raise ConverterError(
                    "ImageMagick timed out after 300s.",
                    backend="imagemagick",
                ) from exc

            if proc.returncode != 0:
                stderr_text = proc.stderr.decode(errors="replace")
                if "not authorized" in stderr_text.lower():
                    raise ConverterError(
                        "ImageMagick PDF conversion blocked by security policy. "
                        "Edit /etc/ImageMagick-*/policy.xml to allow PDF reads:\n"
                        '  <policy domain="coder" rights="read" pattern="PDF" />',
                        backend="imagemagick",
                        stderr_output=stderr_text,
                    )
                raise ConverterError(
                    f"ImageMagick failed (rc={proc.returncode}):\n{stderr_text}",
                    backend="imagemagick",
                    stderr_output=stderr_text,
                )

            png_files = sorted(Path(tmpdir).glob("frame*.png"))
            if not png_files:
                raise ConverterError(
                    "ImageMagick produced no output files.",
                    backend="imagemagick",
                )

            results: list[Image.Image] = []
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


BACKEND_PRIORITY: list[type] = [
    PdftoppmBackend,
    PyMuPDFBackend,
    Pdf2ImageBackend,
    GhostscriptBackend,
    ImageMagickBackend,
]

_BACKEND_BY_NAME: dict[str, type] = {cls.name: cls for cls in BACKEND_PRIORITY}


def get_backend_by_name(name: str) -> ConversionBackend:
    """Instantiate a rasterization backend by its short name.

    Args:
        name: Backend identifier (e.g. ``"pdftoppm"``, ``"pymupdf"``).

    Returns:
        An initialized ``ConversionBackend`` instance.

    Raises:
        ValueError: If *name* is not a recognized backend.
        ConverterNotFoundError: If the backend is not available on this system.
    """
    cls = _BACKEND_BY_NAME.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown backend '{name}'. "
            f"Available: {list(_BACKEND_BY_NAME.keys())}"
        )
    if not cls.is_available():
        raise ConverterNotFoundError(
            f"Backend '{name}' is not available on this system.",
            backend=name,
            install_hint=cls.install_hint(),
        )
    return cls()
