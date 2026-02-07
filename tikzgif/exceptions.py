"""
Custom exception hierarchy for tikzgif.

All tikzgif exceptions inherit from TikzGifError so callers can catch
the entire family with a single except clause.
"""

from __future__ import annotations


class TikzGifError(Exception):
    """Base exception for all tikzgif errors."""


class LatexNotFoundError(TikzGifError):
    """Raised when the requested LaTeX engine is not on $PATH."""


class CompilationError(TikzGifError):
    """Raised when a LaTeX compilation fails."""

    def __init__(self, message: str, log_content: str = "") -> None:
        super().__init__(message)
        self.log_content = log_content


class ConverterError(TikzGifError):
    """Raised when PDF-to-PNG conversion fails."""


class ConverterNotFoundError(TikzGifError):
    """Raised when no PDF-to-PNG converter is available on $PATH."""


class TemplateError(TikzGifError):
    """Raised when template rendering fails."""


class CacheError(TikzGifError):
    """Raised when the frame cache is corrupted or inaccessible."""


class BoundingBoxError(TikzGifError):
    """Raised when bounding box extraction or normalization fails."""
