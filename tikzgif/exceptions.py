"""Custom exception hierarchy for tikzgif.

All tikzgif exceptions inherit from ``TikzGifError`` so callers can
catch the entire family with a single ``except`` clause.
"""

from __future__ import annotations


class TikzGifError(Exception):
    """Base exception for all tikzgif errors."""


class LatexNotFoundError(TikzGifError):
    """Raised when no suitable LaTeX engine is found on ``$PATH``."""

    def __init__(self, message: str, *, engine: str | None = None) -> None:
        super().__init__(message)
        self.engine = engine


class CompilationError(TikzGifError):
    """Raised when one or more LaTeX frames fail to compile.

    Attributes:
        log_content: Raw LaTeX log output, if available.
        frame_index: Index of the frame that triggered the error, if known.
    """

    def __init__(
        self,
        message: str,
        log_content: str = "",
        *,
        frame_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.log_content = log_content
        self.frame_index = frame_index


class ConverterError(TikzGifError):
    """Raised when PDF-to-image rasterization fails.

    Attributes:
        backend: Name of the backend that failed.
        stderr_output: Raw stderr from the conversion subprocess, if available.
    """

    def __init__(
        self,
        message: str,
        *,
        backend: str = "",
        stderr_output: str = "",
    ) -> None:
        super().__init__(message)
        self.backend = backend
        self.stderr_output = stderr_output


class ConverterNotFoundError(TikzGifError):
    """Raised when no PDF-to-image converter is available on ``$PATH``.

    Attributes:
        backend: Name of the unavailable backend.
        install_hint: Platform-specific installation instructions.
    """

    def __init__(
        self,
        message: str,
        *,
        backend: str = "",
        install_hint: str = "",
    ) -> None:
        super().__init__(message)
        self.backend = backend
        self.install_hint = install_hint


class TemplateError(TikzGifError):
    """Raised when template parsing or parameter substitution fails."""


class CacheError(TikzGifError):
    """Raised when the frame cache is corrupted or inaccessible."""


class BoundingBoxError(TikzGifError):
    """Raised when bounding-box extraction or normalization fails."""


class AssemblyError(TikzGifError):
    """Raised when frame assembly into GIF or MP4 fails.

    Attributes:
        output_format: Target format that failed (``"gif"`` or ``"mp4"``).
    """

    def __init__(self, message: str, *, output_format: str = "") -> None:
        super().__init__(message)
        self.output_format = output_format


class RenderError(TikzGifError):
    """Raised when the top-level render pipeline fails.

    Attributes:
        stage: Pipeline stage where the failure occurred.
    """

    def __init__(self, message: str, *, stage: str = "") -> None:
        super().__init__(message)
        self.stage = stage
