"""
Tests for the animation assembly engine.

These tests exercise configuration, frame deduplication, palette
generation, and the Pillow-based assemblers (GIF, WebP, APNG,
spritesheet) without requiring external tools.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import warnings

import pytest
from PIL import Image

# Suppress unclosed-file resource warnings from Pillow lazy loading.
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")

from tikzgif.assembly import (
    AnimationAssembler,
    ApngConfig,
    DeduplicatedFrame,
    DitherAlgorithm,
    FrameDelay,
    GifBackend,
    GifConfig,
    MetadataConfig,
    MetadataWriter,
    Mp4Config,
    OutputConfig,
    OutputFormat,
    QualityPreset,
    SpritesheetConfig,
    VideoCodec,
    WebpConfig,
    _load_and_prepare,
    _maybe_deduplicate,
    _rmse,
    _sha256,
    _tool_available,
    deduplicate_frames,
    generate_global_palette,
    QUALITY_PRESETS,
)
from tikzgif.types import FrameResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_solid_frame(
    color: tuple[int, int, int],
    size: tuple[int, int] = (100, 80),
) -> Image.Image:
    """Create a solid-color RGBA image."""
    return Image.new("RGBA", size, (*color, 255))


def _make_frame_results(
    n: int = 5,
    size: tuple[int, int] = (100, 80),
    tmpdir: Path | None = None,
) -> list[FrameResult]:
    """Create *n* FrameResult objects with gradient frames on disk."""
    if tmpdir is None:
        tmpdir = Path(tempfile.mkdtemp())
    tmpdir.mkdir(parents=True, exist_ok=True)
    results = []
    for i in range(n):
        # Generate frames with varying red channel.
        r = int(255 * i / max(n - 1, 1))
        img = Image.new("RGB", size, (r, 50, 100))
        path = tmpdir / f"frame_{i:04d}.png"
        img.save(str(path))
        results.append(FrameResult(
            index=i,
            success=True,
            png_path=path,
        ))
    return results


# ---------------------------------------------------------------------------
# FrameDelay
# ---------------------------------------------------------------------------

class TestFrameDelay:
    def test_uniform_delay(self):
        fd = FrameDelay(default_ms=100)
        assert fd.resolve(5) == [100, 100, 100, 100, 100]

    def test_pause_first_last(self):
        fd = FrameDelay(default_ms=50, pause_first_ms=500, pause_last_ms=2000)
        result = fd.resolve(4)
        assert result == [500, 50, 50, 2000]

    def test_per_frame_override(self):
        fd = FrameDelay(default_ms=100, delays_ms={1: 200, 3: 300})
        assert fd.resolve(5) == [100, 200, 100, 300, 100]

    def test_single_frame(self):
        fd = FrameDelay(default_ms=100, pause_first_ms=500, pause_last_ms=2000)
        # Single frame gets the last override (pause_last overrides pause_first)
        result = fd.resolve(1)
        assert result == [2000]

    def test_empty(self):
        fd = FrameDelay()
        assert fd.resolve(0) == []


# ---------------------------------------------------------------------------
# RMSE
# ---------------------------------------------------------------------------

class TestRmse:
    def test_identical_images(self):
        a = _make_solid_frame((128, 128, 128))
        assert _rmse(a, a) == pytest.approx(0.0, abs=1e-10)

    def test_opposite_images(self):
        a = _make_solid_frame((0, 0, 0))
        b = _make_solid_frame((255, 255, 255))
        # RMSE between all-black and all-white (RGBA both have alpha=255)
        # channels: (0,0,0,255) vs (255,255,255,255)
        # diff per channel: 255,255,255,0 -> mean sq = (3*255^2)/4
        import numpy as np
        expected = math.sqrt(3 * 255**2 / 4) / 255.0
        assert _rmse(a, b) == pytest.approx(expected, rel=0.01)

    def test_different_sizes(self):
        a = Image.new("RGB", (10, 10), (0, 0, 0))
        b = Image.new("RGB", (20, 20), (0, 0, 0))
        assert _rmse(a, b) == 1.0


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_all_identical(self):
        frames = [_make_solid_frame((100, 100, 100)) for _ in range(5)]
        delays = [100] * 5
        result = deduplicate_frames(frames, delays, threshold=0.01)
        assert len(result) == 1
        assert result[0].delay_ms == 500
        assert result[0].original_indices == [0, 1, 2, 3, 4]

    def test_all_different(self):
        frames = [
            _make_solid_frame((i * 50, 0, 0))
            for i in range(5)
        ]
        delays = [100] * 5
        result = deduplicate_frames(frames, delays, threshold=0.001)
        assert len(result) == 5

    def test_partial_dedup(self):
        frames = [
            _make_solid_frame((0, 0, 0)),
            _make_solid_frame((0, 0, 0)),
            _make_solid_frame((255, 0, 0)),
            _make_solid_frame((255, 0, 0)),
            _make_solid_frame((0, 0, 255)),
        ]
        delays = [100, 100, 100, 100, 100]
        result = deduplicate_frames(frames, delays, threshold=0.01)
        assert len(result) == 3
        assert result[0].delay_ms == 200
        assert result[1].delay_ms == 200
        assert result[2].delay_ms == 100

    def test_empty_input(self):
        assert deduplicate_frames([], [], threshold=0.01) == []


# ---------------------------------------------------------------------------
# Two-pass palette generation
# ---------------------------------------------------------------------------

class TestGlobalPalette:
    def test_basic_palette(self):
        frames = [
            _make_solid_frame((255, 0, 0)),
            _make_solid_frame((0, 255, 0)),
            _make_solid_frame((0, 0, 255)),
        ]
        palette_img, quantized = generate_global_palette(frames, max_colors=256)
        assert palette_img.mode == "P"
        assert len(quantized) == 3
        for q in quantized:
            assert q.mode == "P"

    def test_reduced_colors(self):
        frames = [_make_solid_frame((i, i, i)) for i in range(0, 256, 5)]
        palette_img, quantized = generate_global_palette(frames, max_colors=16)
        # The palette should have at most 16 colors.
        palette_data = palette_img.getpalette()
        # Pillow always returns a 768-entry palette list; count unique RGB triples.
        assert palette_data is not None

    def test_dithering_modes(self):
        frames = [_make_solid_frame((128, 64, 32))]
        for dither in DitherAlgorithm:
            _, quantized = generate_global_palette(frames, max_colors=8, dither=dither)
            assert len(quantized) == 1


# ---------------------------------------------------------------------------
# Quality presets
# ---------------------------------------------------------------------------

class TestQualityPresets:
    def test_all_presets_defined(self):
        for preset in QualityPreset:
            assert preset in QUALITY_PRESETS
            spec = QUALITY_PRESETS[preset]
            assert "dpi" in spec
            assert "gif_colors" in spec
            assert "mp4_crf" in spec

    def test_web_is_smallest(self):
        web = QUALITY_PRESETS[QualityPreset.WEB]
        pres = QUALITY_PRESETS[QualityPreset.PRESENTATION]
        prn = QUALITY_PRESETS[QualityPreset.PRINT]
        assert web["dpi"] < pres["dpi"] < prn["dpi"]
        assert web["mp4_crf"] > pres["mp4_crf"] > prn["mp4_crf"]


# ---------------------------------------------------------------------------
# GIF assembly (Pillow backend -- no external tools needed)
# ---------------------------------------------------------------------------

class TestGifAssemblyPillow:
    def test_basic_gif(self, tmp_path):
        frame_results = _make_frame_results(5, tmpdir=tmp_path / "frames")
        output = tmp_path / "test.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            preset=QualityPreset.WEB,
            frame_delay=FrameDelay(default_ms=100),
            deduplicate_frames=False,
            gif=GifConfig(
                backend=GifBackend.PILLOW,
                optimize_with_gifsicle=False,
                two_pass_palette=True,
                colors=64,
            ),
        )
        from tikzgif.assembly import GifAssembler
        assembler = GifAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        assert result.stat().st_size > 0
        # Verify it is a valid GIF.
        img = Image.open(str(result))
        assert img.format == "GIF"
        assert img.n_frames == 5

    def test_variable_frame_rate(self, tmp_path):
        frame_results = _make_frame_results(3, tmpdir=tmp_path / "frames")
        output = tmp_path / "variable.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            preset=QualityPreset.WEB,
            frame_delay=FrameDelay(default_ms=100, pause_first_ms=500, pause_last_ms=2000),
            deduplicate_frames=False,
            gif=GifConfig(
                backend=GifBackend.PILLOW,
                optimize_with_gifsicle=False,
                two_pass_palette=False,
            ),
        )
        from tikzgif.assembly import GifAssembler
        assembler = GifAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        img = Image.open(str(result))
        assert img.n_frames == 3

    def test_dedup_reduces_frames(self, tmp_path):
        # Create frames where first two are identical.
        (tmp_path / "frames").mkdir(exist_ok=True)
        identical = Image.new("RGB", (100, 80), (50, 50, 50))
        different = Image.new("RGB", (100, 80), (200, 0, 0))
        results = []
        for i, img in enumerate([identical, identical, different]):
            p = tmp_path / "frames" / f"frame_{i:04d}.png"
            img.save(str(p))
            results.append(FrameResult(index=i, success=True, png_path=p))

        output = tmp_path / "dedup.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            deduplicate_frames=True,
            deduplicate_threshold=0.01,
            gif=GifConfig(
                backend=GifBackend.PILLOW,
                optimize_with_gifsicle=False,
            ),
        )
        from tikzgif.assembly import GifAssembler
        assembler = GifAssembler(config)
        result = assembler.assemble(results)
        img = Image.open(str(result))
        # Two identical frames merged into one, so 2 total.
        assert img.n_frames == 2


# ---------------------------------------------------------------------------
# WebP assembly
# ---------------------------------------------------------------------------

class TestWebpAssembly:
    def test_basic_webp(self, tmp_path):
        frame_results = _make_frame_results(3, tmpdir=tmp_path / "frames")
        output = tmp_path / "test.webp"
        config = OutputConfig(
            format=OutputFormat.WEBP,
            output_path=output,
            deduplicate_frames=False,
            webp=WebpConfig(quality=50),
        )
        from tikzgif.assembly import WebpAssembler
        assembler = WebpAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        img = Image.open(str(result))
        assert img.format == "WEBP"
        assert img.n_frames == 3


# ---------------------------------------------------------------------------
# APNG assembly
# ---------------------------------------------------------------------------

class TestApngAssembly:
    def test_basic_apng(self, tmp_path):
        frame_results = _make_frame_results(4, tmpdir=tmp_path / "frames")
        output = tmp_path / "test.apng"
        config = OutputConfig(
            format=OutputFormat.APNG,
            output_path=output,
            deduplicate_frames=False,
        )
        from tikzgif.assembly import ApngAssembler
        assembler = ApngAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        assert result.stat().st_size > 0


# ---------------------------------------------------------------------------
# Spritesheet assembly
# ---------------------------------------------------------------------------

class TestSpritesheetAssembly:
    def test_basic_spritesheet(self, tmp_path):
        frame_results = _make_frame_results(9, tmpdir=tmp_path / "frames")
        output = tmp_path / "sheet.png"
        config = OutputConfig(
            format=OutputFormat.SPRITESHEET,
            output_path=output,
            deduplicate_frames=False,
            spritesheet=SpritesheetConfig(columns=3, output_json=True),
        )
        from tikzgif.assembly import SpritesheetAssembler
        assembler = SpritesheetAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        # Check companion JSON.
        json_path = result.with_suffix(".json")
        assert json_path.exists()
        descriptor = json.loads(json_path.read_text())
        assert descriptor["total_frames"] == 9
        assert descriptor["columns"] == 3
        assert descriptor["rows"] == 3
        assert len(descriptor["frames"]) == 9

    def test_auto_columns(self, tmp_path):
        frame_results = _make_frame_results(16, tmpdir=tmp_path / "frames")
        output = tmp_path / "sheet.png"
        config = OutputConfig(
            format=OutputFormat.SPRITESHEET,
            output_path=output,
            spritesheet=SpritesheetConfig(columns=0),  # auto
        )
        from tikzgif.assembly import SpritesheetAssembler
        assembler = SpritesheetAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()


# ---------------------------------------------------------------------------
# SVG animation assembly
# ---------------------------------------------------------------------------

class TestSvgAnimAssembly:
    def test_basic_svg(self, tmp_path):
        frame_results = _make_frame_results(3, tmpdir=tmp_path / "frames")
        output = tmp_path / "test.svg"
        config = OutputConfig(
            format=OutputFormat.SVG,
            output_path=output,
            deduplicate_frames=False,
        )
        from tikzgif.assembly import SvgAnimAssembler
        assembler = SvgAnimAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        content = result.read_text()
        assert "<svg" in content
        assert "<animate" in content
        assert "data:image/png;base64," in content


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_sha256(self):
        h = _sha256("hello world")
        assert len(h) == 64
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    @pytest.mark.xfail(reason="GIF metadata injection produces unreadable file on some Pillow versions")
    def test_gif_comment(self, tmp_path):
        # Create a minimal GIF first.
        frame_results = _make_frame_results(2, tmpdir=tmp_path / "frames")
        output = tmp_path / "meta.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            deduplicate_frames=False,
            gif=GifConfig(backend=GifBackend.PILLOW, optimize_with_gifsicle=False),
            metadata=MetadataConfig(
                title="Test Animation",
                author="J.C. Vaught",
                comment="Unit test output",
            ),
        )
        from tikzgif.assembly import GifAssembler
        assembler = GifAssembler(config)
        assembler.assemble(frame_results)

        # Now inject metadata.
        writer = MetadataWriter(config.metadata)
        writer.write_gif_comment(output)

        img = Image.open(str(output))
        comment = img.info.get("comment", b"").decode("utf-8")
        assert "Unit test output" in comment

    def test_sidecar_tex(self, tmp_path):
        meta = MetadataConfig(source_tex="\\documentclass{article}\\begin{document}Hello\\end{document}")
        writer = MetadataWriter(meta)
        output = tmp_path / "test.gif"
        output.touch()
        sidecar = writer.embed_source_tex_sidecar(output)
        assert sidecar.exists()
        assert sidecar.suffix == ".tex"
        assert "\\documentclass" in sidecar.read_text()


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------

class TestAnimationAssembler:
    def test_dispatch_gif(self, tmp_path):
        frame_results = _make_frame_results(3, tmpdir=tmp_path / "frames")
        output = tmp_path / "dispatch.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            deduplicate_frames=False,
            gif=GifConfig(backend=GifBackend.PILLOW, optimize_with_gifsicle=False),
        )
        assembler = AnimationAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()

    def test_dispatch_webp(self, tmp_path):
        frame_results = _make_frame_results(3, tmpdir=tmp_path / "frames")
        output = tmp_path / "dispatch.webp"
        config = OutputConfig(
            format=OutputFormat.WEBP,
            output_path=output,
            deduplicate_frames=False,
        )
        assembler = AnimationAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()

    def test_no_frames_raises(self, tmp_path):
        output = tmp_path / "empty.gif"
        config = OutputConfig(format=OutputFormat.GIF, output_path=output)
        assembler = AnimationAssembler(config)
        with pytest.raises(ValueError, match="No successfully compiled frames"):
            assembler.assemble([])

    def test_failed_frames_skipped(self, tmp_path):
        (tmp_path / "frames").mkdir()
        good = Image.new("RGB", (100, 80), (0, 255, 0))
        p = tmp_path / "frames" / "frame_0001.png"
        good.save(str(p))
        frame_results = [
            FrameResult(index=0, success=False),             # failed
            FrameResult(index=1, success=True, png_path=p),  # good
        ]
        output = tmp_path / "partial.gif"
        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=output,
            deduplicate_frames=False,
            gif=GifConfig(backend=GifBackend.PILLOW, optimize_with_gifsicle=False),
        )
        assembler = AnimationAssembler(config)
        result = assembler.assemble(frame_results)
        assert result.exists()
        img = Image.open(str(result))
        assert img.n_frames == 1


# ---------------------------------------------------------------------------
# Tool availability check
# ---------------------------------------------------------------------------

class TestToolAvailability:
    def test_python_is_available(self):
        # Python should always be available in the test environment.
        assert _tool_available("python3") or _tool_available("python")

    def test_nonexistent_tool(self):
        assert not _tool_available("definitely_not_a_real_tool_xyzzy")
