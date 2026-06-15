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
from tikzgif.exceptions import (
    AssemblyError,
    BoundingBoxError,
    CacheError,
    CompilationError,
    ConverterError,
    ConverterNotFoundError,
    LatexNotFoundError,
    RenderError,
    TemplateError,
    TikzGifError,
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
    "AssemblyError",
    "BoundingBox",
    "BoundingBoxError",
    "CacheError",
    "CompilationConfig",
    "CompilationError",
    "CompileConfig",
    "ConverterError",
    "ConverterNotFoundError",
    "ErrorPolicy",
    "FrameResult",
    "FrameSpec",
    "LatexEngine",
    "LatexNotFoundError",
    "OutputConfig",
    "RasterConfig",
    "RenderError",
    "RenderJobConfig",
    "RenderResult",
    "TemplateConfig",
    "TemplateError",
    "TikzGifError",
    "render",
    "render_job",
]
