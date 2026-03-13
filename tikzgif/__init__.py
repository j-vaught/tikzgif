"""
tikzgif -- Parameterized TikZ to animated GIF pipeline.

Compilation engine for splitting parameterized .tex templates into
per-frame documents, compiling them in parallel, and assembling output.
"""

__version__ = "0.1.0"

from tikzgif.api import RenderResult, render, render_job
from tikzgif.config import (
    CompileConfig,
    OutputConfig,
    RasterConfig,
    RenderJobConfig,
    TemplateConfig,
)
from tikzgif.types import (
    BoundingBox,
    CompilationConfig,
    ErrorPolicy,
    FrameResult,
    FrameSpec,
    LatexEngine,
)

__all__ = [
    "BoundingBox",
    "CompilationConfig",
    "ErrorPolicy",
    "FrameResult",
    "FrameSpec",
    "LatexEngine",
    "RenderResult",
    "TemplateConfig",
    "CompileConfig",
    "RasterConfig",
    "OutputConfig",
    "RenderJobConfig",
    "render",
    "render_job",
]
