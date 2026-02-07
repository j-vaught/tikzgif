"""
Tests for frame ordering, validation, and the top-level pipeline.
"""

from __future__ import annotations

import pytest
from PIL import Image

from tikzgif.frames import (
    FrameMap,
    FrameValidation,
    _compute_batch_size,
    _estimate_frame_memory_mb,
    _find_fast_tmpdir,
    validate_frames,
)


# ---------------------------------------------------------------------------
# FrameMap
# ---------------------------------------------------------------------------

class TestFrameMap:
    def test_identity_mapping(self):
        fm = FrameMap.identity(10)
        assert fm.total_frames == 10
        assert fm.total_pdf_pages == 10
        assert fm.page_to_frame[0] == 0
        assert fm.page_to_frame[9] == 9
        assert fm.frame_to_page[5] == 5

    def test_from_page_list(self):
        fm = FrameMap.from_page_list([0, 2, 4, 6], total_pdf_pages=10)
        assert fm.total_frames == 4
        assert fm.total_pdf_pages == 10
        assert fm.frame_to_page[0] == 0
        assert fm.frame_to_page[1] == 2
        assert fm.frame_to_page[3] == 6

    def test_from_range(self):
        fm = FrameMap.from_range(0, 10, step=2, total_pdf_pages=10)
        assert fm.total_frames == 5  # 0, 2, 4, 6, 8
        assert fm.frame_to_page[2] == 4

    def test_from_range_default_step(self):
        fm = FrameMap.from_range(0, 5)
        assert fm.total_frames == 5


# ---------------------------------------------------------------------------
# Frame validation
# ---------------------------------------------------------------------------

def _make_frame(w: int = 100, h: int = 100, color: str = "red") -> Image.Image:
    return Image.new("RGBA", (w, h), color)


def _make_varied_frame(w: int = 100, h: int = 100, seed: int = 0) -> Image.Image:
    """Create a frame with non-uniform content (passes solid-colour check)."""
    img = Image.new("RGBA", (w, h), "white")
    # Draw a small coloured square offset by seed.
    cx = 10 + (seed * 7) % (w - 20)
    cy = 10 + (seed * 11) % (h - 20)
    for x in range(cx, min(cx + 10, w)):
        for y in range(cy, min(cy + 10, h)):
            img.putpixel((x, y), (200, 50, 50, 255))
    return img


class TestValidateFrames:
    def test_valid_uniform_frames(self):
        # Use varied frames so the solid-colour check does not flag them.
        frames = [_make_varied_frame(seed=i) for i in range(5)]
        v = validate_frames(frames)
        assert v.valid
        assert v.total_frames == 5
        assert len(v.corrupt_indices) == 0

    def test_empty_list(self):
        v = validate_frames([])
        assert not v.valid

    def test_none_frame_detected(self):
        frames = [_make_frame(), None, _make_frame()]
        v = validate_frames(frames)
        assert not v.valid
        assert 1 in v.corrupt_indices

    def test_dimension_mismatch(self):
        frames = [
            _make_frame(100, 100),
            _make_frame(200, 200),
        ]
        v = validate_frames(frames, expected_size=(100, 100))
        assert not v.valid
        assert len(v.dimension_mismatches) == 1
        assert v.dimension_mismatches[0][0] == 1

    def test_solid_color_frame_flagged(self):
        """A fully solid-color frame is flagged as potentially empty."""
        frames = [_make_frame(100, 100, "white")]
        v = validate_frames(frames)
        assert not v.valid
        assert 0 in v.empty_indices


# ---------------------------------------------------------------------------
# Memory estimation
# ---------------------------------------------------------------------------

class TestMemoryEstimation:
    def test_frame_memory_calculation(self):
        # 1000x1000 RGBA = 4 MB
        mb = _estimate_frame_memory_mb(1000, 1000)
        assert abs(mb - 4000000 / (1024 * 1024)) < 0.1

    def test_batch_size_small_frames(self):
        batch = _compute_batch_size(
            n_frames=100,
            dpi=72,
            page_width_pt=100,
            page_height_pt=100,
            max_memory_mb=100,
        )
        assert batch >= 1
        assert batch <= 100

    def test_batch_size_large_frames(self):
        batch = _compute_batch_size(
            n_frames=100,
            dpi=600,
            page_width_pt=612,
            page_height_pt=792,
            max_memory_mb=512,
        )
        assert batch >= 1
        # At 600 DPI, frames are ~5100x6600 = ~134 MB each (x3 = 402 MB),
        # so batch size should be 1.
        assert batch <= 5

    def test_batch_size_never_zero(self):
        batch = _compute_batch_size(
            n_frames=1, dpi=1200,
            max_memory_mb=1,
        )
        assert batch >= 1


# ---------------------------------------------------------------------------
# Temp directory detection
# ---------------------------------------------------------------------------

class TestFastTmpdir:
    def test_returns_writable_path(self):
        p = _find_fast_tmpdir()
        assert p.is_dir()
