"""
Tests for the content-addressable compilation cache.
"""

import os
import time

import pytest
from pathlib import Path

from tikzgif.cache import CompilationCache, default_cache_dir
from tikzgif.types import BoundingBox, FrameSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_cache(tmp_path):
    """Create a cache rooted in a temporary directory."""
    return CompilationCache(root=tmp_path / "test_cache")


@pytest.fixture
def sample_spec():
    return FrameSpec(
        index=0,
        param_value=1.5,
        param_name=r"\PARAM",
        tex_content=r"\documentclass{standalone}\begin{document}Hello\end{document}",
        content_hash="abc123def456789012345678901234567890123456789012345678901234",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCompilationCache:
    def test_initial_state(self, tmp_cache):
        assert not tmp_cache.has_frame("nonexistent_hash_value_here")
        assert tmp_cache.get_pdf_path("nonexistent_hash_value") is None
        assert tmp_cache.get_bbox("nonexistent_hash_value") is None

    def test_store_and_retrieve_tex(self, tmp_cache, sample_spec):
        tex_path = tmp_cache.store_tex(sample_spec)
        assert tex_path.is_file()
        assert tex_path.read_text() == sample_spec.tex_content

    def test_has_frame_after_pdf_exists(self, tmp_cache, sample_spec):
        frame_dir = tmp_cache.frame_dir(sample_spec.content_hash)
        pdf = frame_dir / "frame.pdf"
        pdf.write_bytes(b"%PDF-fake")
        assert tmp_cache.has_frame(sample_spec.content_hash)
        assert tmp_cache.get_pdf_path(sample_spec.content_hash) == pdf

    def test_bbox_roundtrip(self, tmp_cache):
        bbox = BoundingBox(x_min=1.5, y_min=2.5, x_max=100.0, y_max=200.0)
        h = "test_bbox_hash_" + "0" * 48
        tmp_cache.store_bbox(h, bbox)
        loaded = tmp_cache.get_bbox(h)
        assert loaded is not None
        assert loaded.x_min == bbox.x_min
        assert loaded.y_max == bbox.y_max

    def test_template_meta_roundtrip(self, tmp_cache):
        frame_map = {0: "hash_a", 1: "hash_b", 2: "hash_c"}
        tmp_cache.store_template_meta("tmpl_hash_1", frame_map)
        loaded = tmp_cache.load_template_meta("tmpl_hash_1")
        assert loaded == frame_map

    def test_template_meta_missing(self, tmp_cache):
        assert tmp_cache.load_template_meta("no_such_hash") is None

    def test_clear(self, tmp_cache, sample_spec):
        tmp_cache.store_tex(sample_spec)
        tmp_cache.clear()
        assert not tmp_cache.has_frame(sample_spec.content_hash)

    def test_stats(self, tmp_cache, sample_spec):
        tmp_cache.store_tex(sample_spec)
        stats = tmp_cache.stats()
        assert stats["entries"] >= 1
        assert stats["size_mb"] >= 0

    def test_gc_removes_old_entries(self, tmp_cache, sample_spec):
        tex_path = tmp_cache.store_tex(sample_spec)
        # Backdate the file to make it eligible for GC.
        old_time = time.time() - (60 * 86400)  # 60 days ago
        os.utime(tex_path, (old_time, old_time))
        removed = tmp_cache.gc(max_age_days=30)
        assert removed >= 1


class TestDefaultCacheDir:
    def test_returns_path(self):
        d = default_cache_dir()
        assert isinstance(d, Path)
        assert "tikzgif" in str(d)
