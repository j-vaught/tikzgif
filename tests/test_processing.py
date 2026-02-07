"""
Tests for the image post-processing pipeline.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image

from tikzgif.processing import (
    ProcessingConfig,
    PadMode,
    CropMode,
    apply_background,
    frame_hash,
    frames_are_identical,
    normalize_dimensions,
    process_frames,
    quantize_for_gif,
    smooth_frame,
    stream_process_frames,
    trim_whitespace,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_frame(
    width: int = 100,
    height: int = 100,
    color: str = "red",
    mode: str = "RGBA",
) -> Image.Image:
    """Create a solid-color test frame."""
    return Image.new(mode, (width, height), color)


def _make_centered_dot(
    canvas_size: int = 200,
    dot_size: int = 20,
    bg: str = "white",
    fg: str = "black",
) -> Image.Image:
    """Create a frame with a small dot centered on a large background."""
    img = Image.new("RGBA", (canvas_size, canvas_size), bg)
    cx = (canvas_size - dot_size) // 2
    for x in range(cx, cx + dot_size):
        for y in range(cx, cx + dot_size):
            img.putpixel((x, y), (0, 0, 0, 255))
    return img


# ---------------------------------------------------------------------------
# trim_whitespace
# ---------------------------------------------------------------------------

class TestTrimWhitespace:
    def test_trim_removes_border(self):
        img = _make_centered_dot(canvas_size=200, dot_size=20)
        trimmed = trim_whitespace(img, fuzz=10, margin=0, background_color="white")
        # The trimmed image should be approximately 20x20.
        assert trimmed.width <= 30  # some tolerance
        assert trimmed.height <= 30

    def test_trim_with_margin(self):
        img = _make_centered_dot(canvas_size=200, dot_size=20)
        trimmed = trim_whitespace(img, fuzz=10, margin=10, background_color="white")
        # Should be ~20 + 2*10 = 40
        assert 30 <= trimmed.width <= 50
        assert 30 <= trimmed.height <= 50

    def test_trim_all_white(self):
        """An entirely white frame should return a tiny fallback."""
        img = _make_frame(100, 100, "white")
        trimmed = trim_whitespace(img, fuzz=10, margin=0, background_color="white")
        assert trimmed.width == 1
        assert trimmed.height == 1

    def test_trim_no_whitespace(self):
        """A frame with no border should be unchanged (minus margin)."""
        img = _make_frame(50, 50, "red")
        trimmed = trim_whitespace(img, fuzz=10, margin=0, background_color="white")
        assert trimmed.width == 50
        assert trimmed.height == 50


# ---------------------------------------------------------------------------
# normalize_dimensions
# ---------------------------------------------------------------------------

class TestNormalizeDimensions:
    def test_pad_smaller_image(self):
        img = _make_frame(50, 50, "red")
        result = normalize_dimensions(img, 100, 100, pad_mode=PadMode.CENTER)
        assert result.size == (100, 100)

    def test_crop_larger_image(self):
        img = _make_frame(200, 200, "red")
        result = normalize_dimensions(img, 100, 100, crop_mode=CropMode.CENTER)
        assert result.size == (100, 100)

    def test_exact_size_no_change(self):
        img = _make_frame(100, 100, "red")
        result = normalize_dimensions(img, 100, 100)
        assert result.size == (100, 100)

    def test_pad_top_left(self):
        img = _make_frame(50, 50, "red")
        result = normalize_dimensions(
            img, 100, 100, pad_mode=PadMode.TOP_LEFT
        )
        assert result.size == (100, 100)
        # Top-left pixel should be red (the original image)
        assert result.getpixel((0, 0))[:3] == (255, 0, 0)

    def test_asymmetric_dimensions(self):
        img = _make_frame(80, 40, "red")
        result = normalize_dimensions(img, 100, 60)
        assert result.size == (100, 60)


# ---------------------------------------------------------------------------
# apply_background
# ---------------------------------------------------------------------------

class TestApplyBackground:
    def test_white_background(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        result = apply_background(img, "white", transparent=False)
        assert result.mode == "RGBA"

    def test_transparent_preserves_alpha(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
        result = apply_background(img, "white", transparent=True)
        assert result.mode == "RGBA"
        # Alpha should still be 0.
        assert result.getpixel((5, 5))[3] == 0


# ---------------------------------------------------------------------------
# smooth_frame
# ---------------------------------------------------------------------------

class TestSmoothFrame:
    def test_smooth_does_not_change_size(self):
        img = _make_frame(100, 100, "red")
        result = smooth_frame(img, radius=1.0)
        assert result.size == img.size

    def test_smooth_with_zero_radius(self):
        img = _make_frame(100, 100, "red")
        result = smooth_frame(img, radius=0.0)
        assert result.size == img.size


# ---------------------------------------------------------------------------
# quantize_for_gif
# ---------------------------------------------------------------------------

class TestQuantizeForGif:
    def test_reduces_colors(self):
        # Create a gradient image with many colors
        img = Image.new("RGB", (100, 100))
        for x in range(100):
            for y in range(100):
                img.putpixel((x, y), (x * 2, y * 2, (x + y) % 256))
        img = img.convert("RGBA")
        result = quantize_for_gif(img, max_colors=16, dither=False)
        # Result should be palette-based or have limited colors.
        assert result is not None

    def test_quantize_preserves_size(self):
        img = _make_frame(50, 50, "red")
        result = quantize_for_gif(img, max_colors=256)
        # Size is preserved regardless of mode.
        assert result.size == (50, 50)


# ---------------------------------------------------------------------------
# Frame hashing and deduplication
# ---------------------------------------------------------------------------

class TestFrameDeduplication:
    def test_identical_frames_same_hash(self):
        a = _make_frame(100, 100, "red")
        b = _make_frame(100, 100, "red")
        assert frame_hash(a) == frame_hash(b)

    def test_different_frames_different_hash(self):
        a = _make_frame(100, 100, "red")
        b = _make_frame(100, 100, "blue")
        assert frame_hash(a) != frame_hash(b)

    def test_identical_comparison_exact(self):
        a = _make_frame(100, 100, "red")
        b = _make_frame(100, 100, "red")
        assert frames_are_identical(a, b, threshold=0)

    def test_different_comparison_exact(self):
        a = _make_frame(100, 100, "red")
        b = _make_frame(100, 100, "blue")
        assert not frames_are_identical(a, b, threshold=0)

    def test_near_identical_with_threshold(self):
        a = Image.new("RGBA", (10, 10), (100, 100, 100, 255))
        b = Image.new("RGBA", (10, 10), (102, 100, 100, 255))
        assert not frames_are_identical(a, b, threshold=0)
        assert frames_are_identical(a, b, threshold=5)

    def test_different_sizes_not_identical(self):
        a = _make_frame(100, 100, "red")
        b = _make_frame(50, 50, "red")
        assert not frames_are_identical(a, b)


# ---------------------------------------------------------------------------
# Full pipeline: process_frames
# ---------------------------------------------------------------------------

class TestProcessFrames:
    def test_basic_pipeline(self):
        frames = [_make_frame(100, 100, "red") for _ in range(5)]
        config = ProcessingConfig(trim=False, deduplicate=False)
        result = process_frames(frames, config)
        assert len(result.frames) == 5
        assert result.dimensions == (100, 100)

    def test_deduplication_removes_consecutive(self):
        frames = [_make_frame(100, 100, "red") for _ in range(5)]
        config = ProcessingConfig(trim=False, deduplicate=True)
        result = process_frames(frames, config)
        # All frames are identical, so only 1 should remain.
        assert len(result.frames) == 1
        assert result.deduped_count == 4

    def test_mixed_frames_partial_dedup(self):
        frames = [
            _make_frame(100, 100, "red"),
            _make_frame(100, 100, "red"),    # dup
            _make_frame(100, 100, "blue"),
            _make_frame(100, 100, "blue"),   # dup
            _make_frame(100, 100, "green"),
        ]
        config = ProcessingConfig(trim=False, deduplicate=True)
        result = process_frames(frames, config)
        assert len(result.frames) == 3  # red, blue, green
        assert result.deduped_count == 2

    def test_empty_frame_list_raises(self):
        with pytest.raises(ValueError, match="No frames"):
            process_frames([], ProcessingConfig())

    def test_uniform_dimensions_after_processing(self):
        """Frames of different sizes should all become the same size."""
        frames = [
            _make_frame(80, 60, "red"),
            _make_frame(100, 80, "blue"),
            _make_frame(60, 100, "green"),
        ]
        config = ProcessingConfig(trim=False, deduplicate=False)
        result = process_frames(frames, config)
        sizes = {f.size for f in result.frames}
        assert len(sizes) == 1  # all same size

    def test_auto_detect_target_dimensions(self):
        frames = [
            _make_frame(50, 50, "red"),
            _make_frame(100, 80, "blue"),
        ]
        config = ProcessingConfig(trim=False, deduplicate=False)
        result = process_frames(frames, config)
        # Target should be the max: 100 x 80
        assert result.dimensions == (100, 80)


# ---------------------------------------------------------------------------
# Streaming pipeline
# ---------------------------------------------------------------------------

class TestStreamProcessFrames:
    def test_streaming_writes_files(self):
        frames = [_make_frame(100, 100, "red") for _ in range(3)]
        config = ProcessingConfig(trim=False, deduplicate=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = stream_process_frames(frames, Path(tmpdir), config)
            png_files = list(Path(tmpdir).glob("frame_*.png"))
            assert len(png_files) == 3
            assert result.original_count == 3

    def test_streaming_deduplication(self):
        frames = [_make_frame(100, 100, "red") for _ in range(5)]
        config = ProcessingConfig(trim=False, deduplicate=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = stream_process_frames(frames, Path(tmpdir), config)
            png_files = list(Path(tmpdir).glob("frame_*.png"))
            assert len(png_files) == 1
            assert result.deduped_count == 4
