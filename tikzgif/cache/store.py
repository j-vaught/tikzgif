"""Content-addressable compilation cache.

Compiled frames are stored under directories named by the SHA-256 of
their ``.tex`` source.  Unchanged frames are served from cache without
recompilation.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from tikzgif.types import BoundingBox, FrameSpec

logger = logging.getLogger(__name__)


def default_cache_dir() -> Path:
    """Return the platform-appropriate default cache directory.

    Respects ``$XDG_CACHE_HOME`` on Unix and ``%LOCALAPPDATA%`` on
    Windows, falling back to ``~/.cache/tikzgif``.
    """
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        base = Path(xdg)
    elif os.name == "nt":
        base = Path(os.environ.get(
            "LOCALAPPDATA",
            str(Path.home() / "AppData" / "Local"),
        ))
    else:
        base = Path.home() / ".cache"
    return base / "tikzgif"


def _ensure_dir(path: Path) -> Path:
    """Create *path* if it does not exist and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key_dir(root: Path, content_hash: str) -> Path:
    """Return the two-level cache subdirectory for *content_hash*.

    Uses a ``<prefix_2>/<rest>`` split to avoid excessive entries in a
    single directory.
    """
    return root / "frames" / content_hash[:2] / content_hash[2:]


class CompilationCache:
    """Content-addressable cache for compiled LaTeX frames.

    Thread-safe for reads; writes are process-isolated because each
    parallel worker writes to a unique hash directory.

    Args:
        root: Cache root directory, or ``None`` for platform default.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_cache_dir()
        self.frames_dir = self.root / "frames"
        self.meta_dir = self.root / "meta"
        _ensure_dir(self.frames_dir)
        _ensure_dir(self.meta_dir)

    def has_frame(self, content_hash: str) -> bool:
        """Return ``True`` if a compiled PDF exists for *content_hash*."""
        pdf = _key_dir(self.root, content_hash) / "frame.pdf"
        return pdf.is_file()

    def get_pdf_path(self, content_hash: str) -> Path | None:
        """Return the cached PDF path, or ``None`` if not cached."""
        pdf = _key_dir(self.root, content_hash) / "frame.pdf"
        return pdf if pdf.is_file() else None

    def get_png_path(self, content_hash: str) -> Path | None:
        """Return the cached PNG path, or ``None`` if not cached."""
        png = _key_dir(self.root, content_hash) / "frame.png"
        return png if png.is_file() else None

    def get_bbox(self, content_hash: str) -> BoundingBox | None:
        """Return the cached bounding box, or ``None``."""
        bbox_file = _key_dir(self.root, content_hash) / "bbox.json"
        if not bbox_file.is_file():
            return None
        try:
            data = json.loads(bbox_file.read_text("utf-8"))
            return BoundingBox(**data)
        except (json.JSONDecodeError, TypeError, KeyError):
            logger.debug("Corrupt bbox cache entry: %s", bbox_file)
            return None

    def frame_dir(self, content_hash: str) -> Path:
        """Return (and create) the cache directory for *content_hash*."""
        return _ensure_dir(_key_dir(self.root, content_hash))

    def store_tex(self, spec: FrameSpec) -> Path:
        """Write the ``.tex`` source into the cache.

        Args:
            spec: Frame specification containing source and hash.

        Returns:
            Path to the cached ``.tex`` file.
        """
        d = self.frame_dir(spec.content_hash)
        tex_path = d / "frame.tex"
        tex_path.write_text(spec.tex_content, encoding="utf-8")
        return tex_path

    def store_pdf(self, spec: FrameSpec, pdf_path: Path) -> Path:
        """Copy a compiled PDF into the cache.

        Args:
            spec: Frame specification.
            pdf_path: Path to the compiled PDF to cache.

        Returns:
            Path to the cached PDF.
        """
        d = self.frame_dir(spec.content_hash)
        dest = d / "frame.pdf"
        shutil.copy2(pdf_path, dest)
        return dest

    def store_png(self, spec: FrameSpec, png_path: Path) -> Path:
        """Copy a rasterized PNG into the cache.

        Args:
            spec: Frame specification.
            png_path: Path to the PNG to cache.

        Returns:
            Path to the cached PNG.
        """
        d = self.frame_dir(spec.content_hash)
        dest = d / "frame.png"
        shutil.copy2(png_path, dest)
        return dest

    def store_bbox(self, content_hash: str, bbox: BoundingBox) -> None:
        """Persist a bounding box alongside a cached frame.

        Args:
            content_hash: Content hash identifying the frame.
            bbox: Bounding box to store.
        """
        d = self.frame_dir(content_hash)
        bbox_file = d / "bbox.json"
        data = {
            "x_min": bbox.x_min,
            "y_min": bbox.y_min,
            "x_max": bbox.x_max,
            "y_max": bbox.y_max,
        }
        bbox_file.write_text(json.dumps(data), encoding="utf-8")

    def store_template_meta(
        self,
        template_hash: str,
        frame_map: dict[int, str],
    ) -> None:
        """Store a mapping from frame index to content hash for a template.

        Args:
            template_hash: SHA-256 of the template source.
            frame_map: ``{frame_index: content_hash}`` mapping.
        """
        meta_path = self.meta_dir / f"{template_hash}.json"
        data = {
            "template_hash": template_hash,
            "timestamp": time.time(),
            "frames": {str(k): v for k, v in frame_map.items()},
        }
        meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_template_meta(self, template_hash: str) -> dict[int, str] | None:
        """Load a previous frame map, or ``None`` if not found.

        Args:
            template_hash: SHA-256 of the template source.

        Returns:
            ``{frame_index: content_hash}`` mapping, or ``None``.
        """
        meta_path = self.meta_dir / f"{template_hash}.json"
        if not meta_path.is_file():
            return None
        try:
            data = json.loads(meta_path.read_text("utf-8"))
            return {int(k): v for k, v in data["frames"].items()}
        except (json.JSONDecodeError, KeyError):
            logger.debug("Corrupt template meta: %s", meta_path)
            return None

    def gc(self, max_age_days: int = 30) -> int:
        """Remove cache entries older than *max_age_days*.

        Args:
            max_age_days: Maximum age in days before eviction.

        Returns:
            Number of entries removed.
        """
        cutoff = time.time() - (max_age_days * 86400)
        removed = 0
        if not self.frames_dir.is_dir():
            return 0
        for prefix_dir in self.frames_dir.iterdir():
            if not prefix_dir.is_dir():
                continue
            for entry in prefix_dir.iterdir():
                if not entry.is_dir():
                    continue
                tex_file = entry / "frame.tex"
                if tex_file.is_file() and tex_file.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
        return removed

    def clear(self) -> int:
        """Remove the entire cache.

        Returns:
            Number of frame entries that were removed.
        """
        count = 0
        if self.frames_dir.is_dir():
            count = sum(
                1
                for prefix_dir in self.frames_dir.iterdir()
                if prefix_dir.is_dir()
                for entry in prefix_dir.iterdir()
                if entry.is_dir()
            )
        if self.root.is_dir():
            shutil.rmtree(self.root)
        _ensure_dir(self.frames_dir)
        _ensure_dir(self.meta_dir)
        return count

    def stats(self) -> dict[str, Any]:
        """Return cache statistics.

        Returns:
            Dict with ``entries`` count, ``size_mb``, and ``root`` path.
        """
        total = 0
        size_bytes = 0
        if self.frames_dir.is_dir():
            for prefix_dir in self.frames_dir.iterdir():
                if not prefix_dir.is_dir():
                    continue
                for entry in prefix_dir.iterdir():
                    if entry.is_dir():
                        total += 1
                        for f in entry.rglob("*"):
                            if f.is_file():
                                size_bytes += f.stat().st_size
        return {
            "entries": total,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "root": str(self.root),
        }


def get_cache_dir(override: Path | None = None) -> Path:
    """Return the cache root, creating it if necessary."""
    return _ensure_dir(override or default_cache_dir())


def lookup_pdf(cache_dir: Path, frame: FrameSpec) -> Path | None:
    """Check if a cached PDF exists for *frame*."""
    pdf = _key_dir(cache_dir, frame.content_hash) / "frame.pdf"
    return pdf if pdf.exists() else None


def lookup_png(cache_dir: Path, frame: FrameSpec) -> Path | None:
    """Check if a cached PNG exists for *frame*."""
    png = _key_dir(cache_dir, frame.content_hash) / "frame.png"
    return png if png.exists() else None


def store_pdf(cache_dir: Path, frame: FrameSpec, pdf_path: Path) -> Path:
    """Copy a compiled PDF into the cache and return the cached path."""
    key = _ensure_dir(_key_dir(cache_dir, frame.content_hash))
    dest = key / "frame.pdf"
    shutil.copy2(pdf_path, dest)
    return dest


def store_png(cache_dir: Path, frame: FrameSpec, png_path: Path) -> Path:
    """Copy a rasterized PNG into the cache and return the cached path."""
    key = _ensure_dir(_key_dir(cache_dir, frame.content_hash))
    dest = key / "frame.png"
    shutil.copy2(png_path, dest)
    return dest


def clear_cache(cache_dir: Path | None = None) -> int:
    """Remove all cached files and return the number of entries removed."""
    root = get_cache_dir(cache_dir)
    if not root.exists():
        return 0
    count = sum(1 for _ in root.rglob("frame.pdf"))
    shutil.rmtree(root)
    return count
