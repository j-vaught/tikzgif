"""Core data structures used throughout the compilation engine."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path


class LatexEngine(enum.Enum):
    """Supported LaTeX compilation engines."""

    PDFLATEX = "pdflatex"
    XELATEX = "xelatex"
    LUALATEX = "lualatex"


class ErrorPolicy(enum.Enum):
    """Strategy for handling single-frame compilation failures.

    Attributes:
        ABORT: Stop the entire job immediately on first failure.
        SKIP: Skip the failed frame and continue with remaining frames.
        RETRY: Retry once with doubled timeout, then skip on second failure.
    """

    ABORT = "abort"
    SKIP = "skip"
    RETRY = "retry"


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in TeX big points (1 bp = 1/72 inch).

    Attributes:
        x_min: Left edge coordinate.
        y_min: Bottom edge coordinate.
        x_max: Right edge coordinate.
        y_max: Top edge coordinate.
    """

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        """Horizontal span of the bounding box."""
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        """Vertical span of the bounding box."""
        return self.y_max - self.y_min

    def union(self, other: BoundingBox) -> BoundingBox:
        """Return the smallest box enclosing both *self* and *other*."""
        return BoundingBox(
            x_min=min(self.x_min, other.x_min),
            y_min=min(self.y_min, other.y_min),
            x_max=max(self.x_max, other.x_max),
            y_max=max(self.y_max, other.y_max),
        )

    def padded(self, padding_bp: float = 2.0) -> BoundingBox:
        """Return a new box expanded by *padding_bp* on all sides."""
        return BoundingBox(
            x_min=self.x_min - padding_bp,
            y_min=self.y_min - padding_bp,
            x_max=self.x_max + padding_bp,
            y_max=self.y_max + padding_bp,
        )

    def to_tikz_clip(self) -> str:
        """Generate a ``\\useasboundingbox`` command for this box."""
        return (
            f"\\useasboundingbox "
            f"({self.x_min}bp, {self.y_min}bp) "
            f"rectangle "
            f"({self.x_max}bp, {self.y_max}bp);"
        )


@dataclass(frozen=True)
class FrameSpec:
    """Specification for a single animation frame.

    Attributes:
        index: Zero-based frame number.
        param_value: The parameter value substituted for this frame.
        param_name: Token name (e.g. ``"\\PARAM"``).
        tex_content: Complete ``.tex`` source for this frame.
        content_hash: SHA-256 hex digest of *tex_content* (for caching).
    """

    index: int
    param_value: float
    param_name: str
    tex_content: str
    content_hash: str


@dataclass
class FrameResult:
    """Result of compiling a single frame.

    Attributes:
        index: Zero-based frame number.
        success: Whether compilation succeeded.
        pdf_path: Path to the compiled PDF, or ``None`` on failure.
        png_path: Path to the rasterized PNG, or ``None`` if not yet converted.
        error_message: Human-readable error description on failure.
        cached: Whether this result was served from cache.
        compile_time_s: Wall-clock compilation time in seconds.
        bounding_box: Extracted bounding box, or ``None``.
    """

    index: int
    success: bool
    pdf_path: Path | None = None
    png_path: Path | None = None
    error_message: str = ""
    cached: bool = False
    compile_time_s: float = 0.0
    bounding_box: BoundingBox | None = None


@dataclass
class CompilationConfig:
    """Full configuration for a compilation job.

    Attributes:
        engine: LaTeX engine, or ``None`` for auto-detection.
        error_policy: Strategy for handling frame failures.
        max_workers: Number of parallel workers (0 = auto from CPU count).
        shell_escape: Whether to enable ``--shell-escape``.
        extra_args: Additional arguments forwarded to the engine.
        cache_dir: Cache root path, or ``None`` for platform default.
        timeout_per_frame_s: Maximum seconds per frame compilation.
        dpi: Target DPI for rasterization.
    """

    engine: LatexEngine | None = None
    error_policy: ErrorPolicy = ErrorPolicy.RETRY
    max_workers: int = 0
    shell_escape: bool = False
    extra_args: list[str] = field(default_factory=list)
    cache_dir: Path | None = None
    timeout_per_frame_s: float = 30.0
    dpi: int = 300
