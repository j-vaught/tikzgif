"""
Core data structures used throughout the compilation engine.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class LatexEngine(enum.Enum):
    """Supported LaTeX compilation engines."""
    PDFLATEX = "pdflatex"
    XELATEX = "xelatex"
    LUALATEX = "lualatex"


class ErrorPolicy(enum.Enum):
    """What to do when a single frame fails to compile."""
    ABORT = "abort"       # Stop entire job immediately.
    SKIP = "skip"         # Skip the failed frame, continue others.
    RETRY = "retry"       # Retry once, then skip.


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned bounding box in TeX points (bp, 1bp = 1/72 inch)."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    def union(self, other: BoundingBox) -> BoundingBox:
        """Return the smallest box enclosing both boxes."""
        return BoundingBox(
            x_min=min(self.x_min, other.x_min),
            y_min=min(self.y_min, other.y_min),
            x_max=max(self.x_max, other.x_max),
            y_max=max(self.y_max, other.y_max),
        )

    def padded(self, padding_bp: float = 2.0) -> BoundingBox:
        """Return a new box expanded by the given padding on all sides."""
        return BoundingBox(
            x_min=self.x_min - padding_bp,
            y_min=self.y_min - padding_bp,
            x_max=self.x_max + padding_bp,
            y_max=self.y_max + padding_bp,
        )

    def to_tikz_clip(self) -> str:
        """Generate a \\useasboundingbox command for this box."""
        return (
            f"\\useasboundingbox "
            f"({self.x_min}bp, {self.y_min}bp) "
            f"rectangle "
            f"({self.x_max}bp, {self.y_max}bp);"
        )


@dataclass(frozen=True)
class FrameSpec:
    """Specification for a single animation frame."""
    index: int                # 0-based frame number
    param_value: float        # The parameter value for this frame
    param_name: str           # e.g., "\\PARAM" or "\\t"
    tex_content: str          # Complete .tex source for this frame
    content_hash: str         # SHA-256 of tex_content (for caching)


@dataclass
class FrameResult:
    """Result of compiling a single frame."""
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
    """Full configuration for a compilation job."""
    engine: LatexEngine = LatexEngine.PDFLATEX
    error_policy: ErrorPolicy = ErrorPolicy.RETRY
    max_workers: int = 0          # 0 = auto-detect from CPU count
    shell_escape: bool = False
    extra_args: list[str] = field(default_factory=list)
    cache_dir: Path | None = None # None = auto (~/.cache/tikzgif/)
    timeout_per_frame_s: float = 30.0
    bbox_strategy: str = "two-pass"  # "two-pass" | "user" | "postprocess"
    dpi: int = 300
    bbox_padding_bp: float = 2.0  # Extra padding around computed envelope
    max_probes: int = 10          # Max frames to probe in two-pass strategy
