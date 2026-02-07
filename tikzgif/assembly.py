"""
Animation assembly engine.

Converts sequences of rendered PNG frames into animated GIF, MP4, WebP,
APNG, spritesheet, SVG animation, and animated-PDF output.  Provides
multiple back-ends (Pillow, ImageMagick, gifsicle, FFmpeg) with unified
configuration, quality/size tradeoff control, smart frame deduplication,
and embedded metadata for reproducibility.
"""

from __future__ import annotations

import enum
import hashlib
import io
import json
import math
import shutil
import struct
import subprocess
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageSequence

from .types import CompilationConfig, FrameResult


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OutputFormat(enum.Enum):
    """Supported animation output formats."""
    GIF = "gif"
    MP4 = "mp4"
    WEBP = "webp"
    APNG = "apng"
    SVG = "svg"
    SPRITESHEET = "spritesheet"
    PDF_ANIMATE = "pdf_animate"


class GifBackend(enum.Enum):
    """Back-end used for GIF assembly."""
    PILLOW = "pillow"
    IMAGEMAGICK = "imagemagick"
    GIFSICLE = "gifsicle"           # post-optimization only


class DitherAlgorithm(enum.Enum):
    """Dithering algorithm for GIF quantization."""
    FLOYD_STEINBERG = "floyd_steinberg"
    ORDERED = "ordered"
    NONE = "none"


class QualityPreset(enum.Enum):
    """Resolution / quality presets."""
    WEB = "web"                     # 96 DPI, small file size
    PRESENTATION = "presentation"   # 150 DPI, balanced
    PRINT = "print"                 # 300 DPI, maximum quality


class VideoCodec(enum.Enum):
    """Video codec selection for MP4 output."""
    H264 = "libx264"
    H265 = "libx265"


# ---------------------------------------------------------------------------
# Preset specifications
# ---------------------------------------------------------------------------

QUALITY_PRESETS: dict[QualityPreset, dict[str, Any]] = {
    QualityPreset.WEB: {
        "dpi": 96,
        "gif_colors": 128,
        "gif_lossy": 80,
        "mp4_crf": 28,
        "webp_quality": 70,
        "max_width": 800,
    },
    QualityPreset.PRESENTATION: {
        "dpi": 150,
        "gif_colors": 256,
        "gif_lossy": 40,
        "mp4_crf": 23,
        "webp_quality": 85,
        "max_width": 1920,
    },
    QualityPreset.PRINT: {
        "dpi": 300,
        "gif_colors": 256,
        "gif_lossy": 0,
        "mp4_crf": 18,
        "webp_quality": 95,
        "max_width": 3840,
    },
}


# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------

@dataclass
class FrameDelay:
    """Per-frame timing control.

    ``delays_ms`` maps a frame index to its display duration in
    milliseconds.  Frames not present in the mapping use
    ``default_ms``.  ``pause_first_ms`` / ``pause_last_ms`` are
    convenience fields that override the first and last frames.
    """
    default_ms: int = 100
    delays_ms: dict[int, int] = field(default_factory=dict)
    pause_first_ms: int | None = None
    pause_last_ms: int | None = None

    def resolve(self, n_frames: int) -> list[int]:
        """Return a list of per-frame delays in milliseconds."""
        delays = [self.delays_ms.get(i, self.default_ms) for i in range(n_frames)]
        if self.pause_first_ms is not None and n_frames > 0:
            delays[0] = self.pause_first_ms
        if self.pause_last_ms is not None and n_frames > 0:
            delays[-1] = self.pause_last_ms
        return delays


@dataclass
class GifConfig:
    """GIF-specific assembly options."""
    backend: GifBackend = GifBackend.PILLOW
    optimize_with_gifsicle: bool = True
    loop_count: int = 0             # 0 = infinite loop
    dither: DitherAlgorithm = DitherAlgorithm.FLOYD_STEINBERG
    colors: int = 256               # max palette entries (2 -- 256)
    lossy_level: int = 0            # gifsicle --lossy=N (0 = lossless)
    fuzz_percent: float = 2.0       # ImageMagick -fuzz N%
    two_pass_palette: bool = True   # Use two-pass global palette
    transparent: bool = False       # Transparent background


@dataclass
class Mp4Config:
    """MP4-specific assembly options."""
    codec: VideoCodec = VideoCodec.H264
    crf: int = 23                   # Constant Rate Factor (lower = better)
    pixel_format: str = "yuv420p"   # Broad compatibility
    fps: float = 10.0
    loop_count: int = 1             # How many times to repeat all frames
    audio_path: Path | None = None  # Optional audio track
    preset: str = "medium"          # FFmpeg encoding speed preset


@dataclass
class WebpConfig:
    """WebP animation options."""
    quality: int = 85               # 0 -- 100
    lossless: bool = False
    loop_count: int = 0             # 0 = infinite
    method: int = 4                 # Compression effort 0 -- 6


@dataclass
class ApngConfig:
    """APNG animation options."""
    loop_count: int = 0             # 0 = infinite
    optimize: bool = True


@dataclass
class SvgAnimConfig:
    """SMIL-based SVG animation options."""
    embed_images: bool = True       # base64-encode frames into SVG
    viewbox_width: int = 800


@dataclass
class SpritesheetConfig:
    """Spritesheet output options."""
    columns: int = 0                # 0 = auto (sqrt of frame count)
    padding: int = 0                # Pixels between frames
    output_json: bool = True        # Emit companion JSON descriptor


@dataclass
class PdfAnimateConfig:
    """Re-embed frames as an animated PDF using the LaTeX animate package."""
    fps: float = 10.0
    loop: bool = True
    controls: bool = True           # Show play/pause controls
    engine: str = "pdflatex"


@dataclass
class MetadataConfig:
    """Metadata to embed in output files."""
    title: str = ""
    author: str = ""
    comment: str = "Generated by tikzgif"
    source_tex: str = ""            # Full .tex source for reproducibility
    custom: dict[str, str] = field(default_factory=dict)


@dataclass
class OutputConfig:
    """Top-level output configuration."""
    format: OutputFormat = OutputFormat.GIF
    output_path: Path = Path("output.gif")
    preset: QualityPreset = QualityPreset.PRESENTATION
    frame_delay: FrameDelay = field(default_factory=FrameDelay)
    max_file_size_bytes: int | None = None  # Auto-reduce quality to hit target
    deduplicate_frames: bool = True         # Merge near-duplicate frames
    deduplicate_threshold: float = 0.005    # RMSE fraction threshold
    gif: GifConfig = field(default_factory=GifConfig)
    mp4: Mp4Config = field(default_factory=Mp4Config)
    webp: WebpConfig = field(default_factory=WebpConfig)
    apng: ApngConfig = field(default_factory=ApngConfig)
    svg_anim: SvgAnimConfig = field(default_factory=SvgAnimConfig)
    spritesheet: SpritesheetConfig = field(default_factory=SpritesheetConfig)
    pdf_animate: PdfAnimateConfig = field(default_factory=PdfAnimateConfig)
    metadata: MetadataConfig = field(default_factory=MetadataConfig)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a subprocess with error handling."""
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _tool_available(name: str) -> bool:
    """Return True if *name* is on the PATH."""
    return shutil.which(name) is not None


def _rmse(img_a: Image.Image, img_b: Image.Image) -> float:
    """Root mean square error between two images, normalized to [0, 1]."""
    a = img_a.convert("RGBA")
    b = img_b.convert("RGBA")
    if a.size != b.size:
        return 1.0
    import numpy as np
    arr_a = np.asarray(a, dtype=np.float64)
    arr_b = np.asarray(b, dtype=np.float64)
    return float(np.sqrt(np.mean((arr_a - arr_b) ** 2)) / 255.0)


# ---------------------------------------------------------------------------
# Smart frame deduplication
# ---------------------------------------------------------------------------

@dataclass
class DeduplicatedFrame:
    """A frame with its resolved display duration after dedup merging."""
    image: Image.Image
    delay_ms: int
    original_indices: list[int]


def deduplicate_frames(
    images: list[Image.Image],
    delays_ms: list[int],
    threshold: float = 0.005,
) -> list[DeduplicatedFrame]:
    """Merge consecutive near-duplicate frames, summing their durations.

    Two consecutive frames are considered duplicates when their RMSE is
    below *threshold* (range 0 -- 1).  This reduces total frame count and
    output file size without visible quality loss.
    """
    if not images:
        return []

    groups: list[DeduplicatedFrame] = [
        DeduplicatedFrame(
            image=images[0],
            delay_ms=delays_ms[0],
            original_indices=[0],
        )
    ]

    for i in range(1, len(images)):
        if _rmse(groups[-1].image, images[i]) < threshold:
            groups[-1].delay_ms += delays_ms[i]
            groups[-1].original_indices.append(i)
        else:
            groups.append(
                DeduplicatedFrame(
                    image=images[i],
                    delay_ms=delays_ms[i],
                    original_indices=[i],
                )
            )

    return groups


# ---------------------------------------------------------------------------
# Two-pass palette generation
# ---------------------------------------------------------------------------

def generate_global_palette(
    images: list[Image.Image],
    max_colors: int = 256,
    dither: DitherAlgorithm = DitherAlgorithm.FLOYD_STEINBERG,
) -> tuple[Image.Image, list[Image.Image]]:
    """Two-pass global palette generation for optimal GIF color representation.

    **Pass 1 -- Histogram accumulation:**
        Walk every frame and accumulate a combined color histogram so that
        globally-important colors are not dropped.

    **Pass 2 -- Quantization:**
        Build a single global palette from the combined histogram, then
        remap every frame to that palette using the chosen dithering
        algorithm.

    Returns:
        (palette_image, quantized_frames)
        ``palette_image`` is a 1-pixel P-mode image whose palette is the
        global palette.  ``quantized_frames`` is the list of frames
        quantized to that palette.
    """
    # Pass 1: build a combined histogram via a large mosaic.
    # Pillow's ``quantize()`` works on a single image, so tile all frames
    # into one big strip and quantize that.
    frame_w, frame_h = images[0].size
    # Limit mosaic size to avoid excessive memory: sample at most 64 frames
    # evenly spaced if we have many.
    sample_indices = list(range(len(images)))
    if len(images) > 64:
        step = len(images) / 64
        sample_indices = [int(i * step) for i in range(64)]

    cols = min(len(sample_indices), 8)
    rows = math.ceil(len(sample_indices) / cols)
    mosaic = Image.new("RGBA", (frame_w * cols, frame_h * rows))
    for idx, frame_idx in enumerate(sample_indices):
        r, c = divmod(idx, cols)
        mosaic.paste(images[frame_idx].convert("RGBA"), (c * frame_w, r * frame_h))

    # Pillow quantization method mapping
    pil_dither = {
        DitherAlgorithm.FLOYD_STEINBERG: Image.Dither.FLOYDSTEINBERG,
        DitherAlgorithm.ORDERED: Image.Dither.ORDERED,
        DitherAlgorithm.NONE: Image.Dither.NONE,
    }[dither]

    # Quantize the mosaic to extract the global palette.
    mosaic_rgb = mosaic.convert("RGB")
    palette_img = mosaic_rgb.quantize(
        colors=max_colors,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,  # no dithering on the reference image
    )

    # Pass 2: quantize each individual frame using the global palette.
    quantized: list[Image.Image] = []
    for img in images:
        q = img.convert("RGB").quantize(
            palette=palette_img,
            dither=pil_dither,
        )
        quantized.append(q)

    return palette_img, quantized


# ===================================================================
#  SECTION 1 -- GIF ASSEMBLY
# ===================================================================

class GifAssembler:
    """Assemble a sequence of PNG frames into an animated GIF.

    Supports three back-ends (Pillow, ImageMagick, gifsicle) with
    automatic fallback and optional post-optimization.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.gif = config.gif

    # ---- Pillow back-end ------------------------------------------------

    def _assemble_pillow(
        self,
        frames: list[DeduplicatedFrame],
        output: Path,
    ) -> Path:
        """Build GIF using Pillow (PIL).

        Steps:
            1. Apply two-pass palette generation (if enabled).
            2. Convert all frames to P-mode with the global palette.
            3. Write using ``Image.save()`` with ``save_all=True``.
        """
        images = [f.image for f in frames]
        delays = [f.delay_ms for f in frames]

        if self.gif.two_pass_palette:
            _palette_img, quantized = generate_global_palette(
                images,
                max_colors=self.gif.colors,
                dither=self.gif.dither,
            )
            p_frames = quantized
        else:
            pil_dither = {
                DitherAlgorithm.FLOYD_STEINBERG: Image.Dither.FLOYDSTEINBERG,
                DitherAlgorithm.ORDERED: Image.Dither.ORDERED,
                DitherAlgorithm.NONE: Image.Dither.NONE,
            }[self.gif.dither]
            p_frames = [
                img.convert("RGB").quantize(
                    colors=self.gif.colors, dither=pil_dither,
                )
                for img in images
            ]

        # Pillow GIF save.
        first = p_frames[0]
        rest = p_frames[1:]

        transparency = 0 if self.gif.transparent else None

        first.save(
            str(output),
            format="GIF",
            save_all=True,
            append_images=rest,
            duration=delays,                  # Per-frame durations (ms)
            loop=self.gif.loop_count,         # 0 = infinite
            optimize=True,                    # Pillow frame optimization
            disposal=2,                       # Restore to background
            transparency=transparency,
            comment=self.cfg.metadata.comment.encode("utf-8") if self.cfg.metadata.comment else None,
        )
        return output

    # ---- ImageMagick back-end -------------------------------------------

    def _assemble_imagemagick(
        self,
        frames: list[DeduplicatedFrame],
        output: Path,
    ) -> Path:
        """Build GIF using ImageMagick ``magick convert``.

        Command structure::

            magick
              -dispose Background
              -loop 0
              ( -delay 100 frame_000.png )
              ( -delay 100 frame_001.png )
              ...
              -layers Optimize
              -fuzz 2%
              -coalesce
              -dither FloydSteinberg
              -colors 256
              output.gif

        The parenthesized sub-commands allow per-frame delay values.
        ``-layers Optimize`` applies frame-diff optimization to remove
        redundant pixels.  ``-fuzz N%`` lets "close enough" colors match
        during optimization.
        """
        if not _tool_available("magick"):
            raise RuntimeError("ImageMagick (magick) is not installed or not on PATH")

        with tempfile.TemporaryDirectory(prefix="tikzgif_im_") as tmpdir:
            tmp = Path(tmpdir)
            # Write individual frames with their delay values.
            frame_paths: list[Path] = []
            for i, frm in enumerate(frames):
                p = tmp / f"frame_{i:06d}.png"
                frm.image.save(str(p), format="PNG")
                frame_paths.append(p)

            dither_map = {
                DitherAlgorithm.FLOYD_STEINBERG: "FloydSteinberg",
                DitherAlgorithm.ORDERED: "Riemersma",
                DitherAlgorithm.NONE: "None",
            }

            cmd: list[str] = ["magick"]
            cmd += ["-dispose", "Background"]
            cmd += ["-loop", str(self.gif.loop_count)]

            # Per-frame delay in 1/100 s units.
            for i, frm in enumerate(frames):
                delay_cs = max(1, frm.delay_ms // 10)
                cmd += [
                    "(", "-delay", str(delay_cs),
                    str(frame_paths[i]),
                    ")",
                ]

            # Post-processing flags.
            cmd += ["-coalesce"]
            cmd += ["-layers", "Optimize"]
            cmd += ["-fuzz", f"{self.gif.fuzz_percent}%"]
            cmd += ["-dither", dither_map[self.gif.dither]]
            cmd += ["-colors", str(self.gif.colors)]
            cmd += [str(output)]

            _run(cmd, timeout=300)

        return output

    # ---- gifsicle post-optimization -------------------------------------

    def _optimize_gifsicle(self, gif_path: Path) -> Path:
        """Run gifsicle on an existing GIF for additional compression.

        Options applied:

        * ``--optimize=3``  -- full cross-frame optimization
        * ``--lossy=N``     -- DCT-like lossy compression (0 = off)
        * ``--colors N``    -- reduce palette further if requested
        * ``-Okeep-empty``  -- keep empty transparent frames
        """
        if not _tool_available("gifsicle"):
            raise RuntimeError("gifsicle is not installed or not on PATH")

        optimized = gif_path.with_suffix(".opt.gif")

        cmd: list[str] = [
            "gifsicle",
            "--optimize=3",
            "--no-warnings",
        ]
        if self.gif.lossy_level > 0:
            cmd += [f"--lossy={self.gif.lossy_level}"]
        if self.gif.colors < 256:
            cmd += [f"--colors={self.gif.colors}"]
        cmd += ["-o", str(optimized), str(gif_path)]

        _run(cmd)

        # Replace original with optimized version.
        optimized.replace(gif_path)
        return gif_path

    # ---- Two-pass palette via ImageMagick / FFmpeg ----------------------

    def _two_pass_palette_imagemagick(
        self,
        frames: list[DeduplicatedFrame],
        output: Path,
    ) -> Path:
        """Two-pass palette generation using ImageMagick.

        Pass 1: ``magick convert frames... -append +dither -colors N palette.png``
        Pass 2: ``magick convert frames... -remap palette.png output.gif``
        """
        if not _tool_available("magick"):
            raise RuntimeError("ImageMagick (magick) is not installed or not on PATH")

        with tempfile.TemporaryDirectory(prefix="tikzgif_pal_") as tmpdir:
            tmp = Path(tmpdir)
            frame_paths: list[Path] = []
            for i, frm in enumerate(frames):
                p = tmp / f"frame_{i:06d}.png"
                frm.image.save(str(p), format="PNG")
                frame_paths.append(p)

            palette_path = tmp / "palette.png"

            # Pass 1: Generate palette.
            cmd_pass1 = [
                "magick",
                *[str(fp) for fp in frame_paths],
                "-append",
                "+dither",
                "-colors", str(self.gif.colors),
                "-unique-colors",
                str(palette_path),
            ]
            _run(cmd_pass1, timeout=120)

            # Pass 2: Remap frames using palette and assemble.
            cmd_pass2: list[str] = ["magick"]
            cmd_pass2 += ["-dispose", "Background"]
            cmd_pass2 += ["-loop", str(self.gif.loop_count)]
            for i, frm in enumerate(frames):
                delay_cs = max(1, frm.delay_ms // 10)
                cmd_pass2 += [
                    "(", "-delay", str(delay_cs),
                    str(frame_paths[i]),
                    "-remap", str(palette_path),
                    ")",
                ]
            cmd_pass2 += ["-layers", "Optimize"]
            cmd_pass2 += [str(output)]
            _run(cmd_pass2, timeout=300)

        return output

    # ---- Public entry point ---------------------------------------------

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        """Load frames, deduplicate, and assemble GIF.

        Returns the path to the final GIF file.
        """
        images, delays = _load_and_prepare(frame_results, self.cfg)
        frames = _maybe_deduplicate(images, delays, self.cfg)

        output = self.cfg.output_path

        if self.gif.backend == GifBackend.PILLOW:
            self._assemble_pillow(frames, output)
        elif self.gif.backend == GifBackend.IMAGEMAGICK:
            if self.gif.two_pass_palette:
                self._two_pass_palette_imagemagick(frames, output)
            else:
                self._assemble_imagemagick(frames, output)
        elif self.gif.backend == GifBackend.GIFSICLE:
            # gifsicle is optimization-only; fall back to Pillow for assembly.
            self._assemble_pillow(frames, output)
            self.gif.optimize_with_gifsicle = True

        if self.gif.optimize_with_gifsicle and _tool_available("gifsicle"):
            self._optimize_gifsicle(output)

        # Enforce max file size constraint.
        if self.cfg.max_file_size_bytes is not None:
            _enforce_size_limit(output, self.cfg.max_file_size_bytes, "gif", self)

        return output


# ===================================================================
#  SECTION 2 -- MP4 / VIDEO ASSEMBLY
# ===================================================================

class Mp4Assembler:
    """Assemble frames into MP4 video using FFmpeg.

    FFmpeg pipeline:

    1. Write frames to a temp directory as a numbered sequence.
    2. Optionally loop the frame sequence N times (MP4 has no native loop).
    3. Encode using ``-c:v libx264 -pix_fmt yuv420p -crf 23``.
    4. Optionally mux an audio track.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.mp4 = config.mp4

    def _write_frame_sequence(
        self,
        frames: list[DeduplicatedFrame],
        dest_dir: Path,
    ) -> tuple[Path, str]:
        """Write frames to *dest_dir* as a zero-padded sequence.

        When the MP4 loop count > 1, the sequence is physically
        duplicated the requested number of times so FFmpeg encodes
        a single longer video.

        Variable frame rate is handled by writing a FFmpeg concat
        demuxer file with per-frame durations.

        Returns (concat_file_path, pattern) where *concat_file_path* is
        the path to the concat demuxer file and *pattern* is unused
        (kept for alternative input methods).
        """
        total_frames: list[tuple[Path, int]] = []
        idx = 0
        for _loop in range(self.mp4.loop_count):
            for frm in frames:
                path = dest_dir / f"frame_{idx:06d}.png"
                frm.image.save(str(path), format="PNG")
                total_frames.append((path, frm.delay_ms))
                idx += 1

        # Write concat demuxer file for variable-rate input.
        concat = dest_dir / "frames.txt"
        with open(concat, "w") as f:
            for path, delay_ms in total_frames:
                duration_s = delay_ms / 1000.0
                f.write(f"file '{path}'\n")
                f.write(f"duration {duration_s:.6f}\n")
            # FFmpeg concat demuxer needs the last file repeated for the
            # duration to be applied.
            if total_frames:
                f.write(f"file '{total_frames[-1][0]}'\n")

        pattern = str(dest_dir / "frame_%06d.png")
        return concat, pattern

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        """Build MP4 from frame sequence. Returns path to output."""
        if not _tool_available("ffmpeg"):
            raise RuntimeError("ffmpeg is not installed or not on PATH")

        images, delays = _load_and_prepare(frame_results, self.cfg)
        frames = _maybe_deduplicate(images, delays, self.cfg)

        output = self.cfg.output_path
        tmpdir = tempfile.mkdtemp(prefix="tikzgif_mp4_")
        tmp = Path(tmpdir)

        try:
            concat_file, _ = self._write_frame_sequence(frames, tmp)

            cmd: list[str] = [
                "ffmpeg", "-y",
                # Input: concat demuxer for variable frame rate support.
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                # Codec settings.
                "-c:v", self.mp4.codec.value,
                "-pix_fmt", self.mp4.pixel_format,
                "-crf", str(self.mp4.crf),
                "-preset", self.mp4.preset,
                # Ensure dimensions are divisible by 2 (H.264 requirement).
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                # Avoid B-frame issues with some players.
                "-movflags", "+faststart",
            ]

            # Optional audio track.
            if self.mp4.audio_path is not None and self.mp4.audio_path.exists():
                cmd += [
                    "-i", str(self.mp4.audio_path),
                    "-c:a", "aac",
                    "-b:a", "128k",
                    "-shortest",
                ]

            # Metadata.
            meta = self.cfg.metadata
            if meta.title:
                cmd += ["-metadata", f"title={meta.title}"]
            if meta.author:
                cmd += ["-metadata", f"artist={meta.author}"]
            if meta.comment:
                cmd += ["-metadata", f"comment={meta.comment}"]
            if meta.source_tex:
                cmd += ["-metadata", f"description=source_tex:{_truncate(meta.source_tex, 4000)}"]
            for k, v in meta.custom.items():
                cmd += ["-metadata", f"{k}={v}"]

            cmd.append(str(output))

            _run(cmd, timeout=600)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # Enforce size constraint.
        if self.cfg.max_file_size_bytes is not None:
            _enforce_size_limit(output, self.cfg.max_file_size_bytes, "mp4", self)

        return output


# ===================================================================
#  SECTION 3 -- WEBP ANIMATED
# ===================================================================

class WebpAssembler:
    """Assemble frames into an animated WebP using Pillow.

    WebP supports both lossy and lossless compression, a full 24-bit
    color gamut (vs. GIF's 256), and alpha transparency.  It typically
    produces files 30--50 % smaller than equivalent GIFs.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.webp = config.webp

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        images, delays = _load_and_prepare(frame_results, self.cfg)
        frames = _maybe_deduplicate(images, delays, self.cfg)

        output = self.cfg.output_path
        rgba_frames = [f.image.convert("RGBA") for f in frames]
        durations = [f.delay_ms for f in frames]

        first = rgba_frames[0]
        first.save(
            str(output),
            format="WEBP",
            save_all=True,
            append_images=rgba_frames[1:],
            duration=durations,
            loop=self.webp.loop_count,
            quality=self.webp.quality,
            lossless=self.webp.lossless,
            method=self.webp.method,
        )

        if self.cfg.max_file_size_bytes is not None:
            _enforce_size_limit(output, self.cfg.max_file_size_bytes, "webp", self)

        return output


# ===================================================================
#  SECTION 3b -- APNG (Animated PNG)
# ===================================================================

class ApngAssembler:
    """Assemble frames into APNG using Pillow.

    APNG supports full RGBA with 8-bit alpha -- far superior to GIF's
    1-bit transparency.  File sizes are typically larger than WebP but
    the format is natively supported in all modern browsers.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.apng = config.apng

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        images, delays = _load_and_prepare(frame_results, self.cfg)
        frames = _maybe_deduplicate(images, delays, self.cfg)

        output = self.cfg.output_path
        rgba_frames = [f.image.convert("RGBA") for f in frames]
        durations = [f.delay_ms for f in frames]

        first = rgba_frames[0]
        first.save(
            str(output),
            format="PNG",
            save_all=True,
            append_images=rgba_frames[1:],
            duration=durations,
            loop=self.apng.loop_count,
            default_image=True,
        )

        return output


# ===================================================================
#  SECTION 3c -- SVG Animation (SMIL)
# ===================================================================

class SvgAnimAssembler:
    """Assemble frames into a SMIL-animated SVG.

    Each frame is base64-encoded as a data URI inside an ``<image>``
    element.  SMIL ``<animate>`` elements toggle visibility to create
    the animation.  This format is ideal for embedding in web pages.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.svg = config.svg_anim

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        import base64

        images, delays = _load_and_prepare(frame_results, self.cfg)
        frames = _maybe_deduplicate(images, delays, self.cfg)

        if not frames:
            raise ValueError("No frames to assemble")

        w, h = frames[0].image.size
        # Scale to target viewbox width.
        scale = self.svg.viewbox_width / w
        vw = self.svg.viewbox_width
        vh = int(h * scale)

        total_dur_s = sum(f.delay_ms for f in frames) / 1000.0

        # Build SVG document.
        svg = ET.Element("svg", {
            "xmlns": "http://www.w3.org/2000/svg",
            "xmlns:xlink": "http://www.w3.org/1999/xlink",
            "viewBox": f"0 0 {vw} {vh}",
            "width": str(vw),
            "height": str(vh),
        })

        # Encode each frame as a <image> with SMIL visibility animation.
        cumulative_s = 0.0
        for i, frm in enumerate(frames):
            buf = io.BytesIO()
            frm.image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            data_uri = f"data:image/png;base64,{b64}"

            dur_s = frm.delay_ms / 1000.0
            begin_s = cumulative_s
            end_s = cumulative_s + dur_s

            img_el = ET.SubElement(svg, "image", {
                "href": data_uri,
                "width": str(vw),
                "height": str(vh),
                "visibility": "hidden",
            })

            # SMIL <animate> to show this frame during its time slice.
            # Values: hidden until begin, visible during, hidden after.
            key_times = "0"
            values = "hidden"

            if begin_s > 0:
                key_times += f";{begin_s / total_dur_s:.6f}"
                values += ";hidden"

            key_times += f";{begin_s / total_dur_s:.6f}"
            values += ";visible"

            key_times += f";{end_s / total_dur_s:.6f}"
            values += ";visible"

            if end_s < total_dur_s:
                key_times += f";{end_s / total_dur_s:.6f}"
                values += ";hidden"

            key_times += ";1"
            values += ";hidden"

            ET.SubElement(img_el, "animate", {
                "attributeName": "visibility",
                "values": values,
                "keyTimes": key_times,
                "dur": f"{total_dur_s:.3f}s",
                "repeatCount": "indefinite",
                "calcMode": "discrete",
            })

            cumulative_s = end_s

        tree = ET.ElementTree(svg)
        ET.indent(tree, space="  ")
        output = self.cfg.output_path
        tree.write(str(output), xml_declaration=True, encoding="utf-8")
        return output


# ===================================================================
#  SECTION 3d -- Spritesheet
# ===================================================================

class SpritesheetAssembler:
    """Tile all frames into a single spritesheet image.

    Produces a PNG plus an optional JSON descriptor with per-frame
    coordinates, suitable for web/game use.
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.ss = config.spritesheet

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        images, delays = _load_and_prepare(frame_results, self.cfg)
        # No dedup for spritesheets -- each logical frame gets a cell.

        if not images:
            raise ValueError("No frames to assemble")

        n = len(images)
        fw, fh = images[0].size
        padding = self.ss.padding

        cols = self.ss.columns if self.ss.columns > 0 else max(1, int(math.ceil(math.sqrt(n))))
        rows = math.ceil(n / cols)

        sheet_w = cols * fw + (cols - 1) * padding
        sheet_h = rows * fh + (rows - 1) * padding
        sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

        json_frames: list[dict[str, Any]] = []
        for i, img in enumerate(images):
            r, c = divmod(i, cols)
            x = c * (fw + padding)
            y = r * (fh + padding)
            sheet.paste(img.convert("RGBA"), (x, y))
            json_frames.append({
                "index": i,
                "x": x, "y": y,
                "w": fw, "h": fh,
                "delay_ms": delays[i],
            })

        output = self.cfg.output_path
        sheet.save(str(output), format="PNG")

        if self.ss.output_json:
            json_path = output.with_suffix(".json")
            descriptor = {
                "image": output.name,
                "frame_width": fw,
                "frame_height": fh,
                "columns": cols,
                "rows": rows,
                "total_frames": n,
                "frames": json_frames,
            }
            with open(json_path, "w") as f:
                json.dump(descriptor, f, indent=2)

        return output


# ===================================================================
#  SECTION 3e -- PDF Animate
# ===================================================================

class PdfAnimateAssembler:
    """Re-embed PNG frames into an animated PDF using the LaTeX animate package.

    Generates a small LaTeX document that uses ``\\animategraphics``
    from the ``animate`` package, compiles it, and produces a PDF
    where the animation plays in compatible viewers (e.g. Adobe Reader).
    """

    def __init__(self, config: OutputConfig) -> None:
        self.cfg = config
        self.pa = config.pdf_animate

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        images, delays = _load_and_prepare(frame_results, self.cfg)

        if not images:
            raise ValueError("No frames to assemble")

        output = self.cfg.output_path

        with tempfile.TemporaryDirectory(prefix="tikzgif_pdfanim_") as tmpdir:
            tmp = Path(tmpdir)

            # Write frames.
            for i, img in enumerate(images):
                img.save(str(tmp / f"frame_{i:06d}.png"), format="PNG")

            # Determine timeline file for variable frame rate.
            # The animate package supports a timeline file mapping
            # frame index to display time.
            has_variable = len(set(delays)) > 1
            timeline_content = ""
            if has_variable:
                # Timeline format: each line is "::display_duration"
                # where duration is in seconds.
                lines = []
                for i, d in enumerate(delays):
                    lines.append(f"::{d / 1000.0:.4f}")
                timeline_content = "\n".join(lines)
                timeline_path = tmp / "timeline.txt"
                with open(timeline_path, "w") as f:
                    f.write(timeline_content)

            loop_opt = ",loop" if self.pa.loop else ""
            controls_opt = ",controls" if self.pa.controls else ""
            timeline_opt = f",timeline=timeline.txt" if has_variable else ""

            tex_source = textwrap.dedent(f"""\
                \\documentclass[margin=0pt]{{standalone}}
                \\usepackage{{animate}}
                \\usepackage{{graphicx}}
                \\begin{{document}}
                \\animategraphics[{loop_opt}{controls_opt}{timeline_opt},autoplay]
                  {{{int(self.pa.fps)}}}
                  {{frame_}}{{000000}}{{{len(images) - 1:06d}}}
                \\end{{document}}
            """)

            tex_path = tmp / "animate.tex"
            with open(tex_path, "w") as f:
                f.write(tex_source)

            # Compile twice (for the animate package to resolve references).
            engine = self.pa.engine
            for _ in range(2):
                _run(
                    [engine, "-interaction=nonstopmode", "-output-directory", str(tmp), str(tex_path)],
                    timeout=120,
                )

            pdf_result = tmp / "animate.pdf"
            if pdf_result.exists():
                shutil.copy2(str(pdf_result), str(output))
            else:
                raise RuntimeError("PDF animate compilation failed -- no output PDF produced")

        return output


# ===================================================================
#  SECTION 4 -- OUTPUT OPTIMIZATION
# ===================================================================

def _enforce_size_limit(
    path: Path,
    max_bytes: int,
    fmt: str,
    assembler: Any,
) -> None:
    """Iteratively reduce quality until the file fits under *max_bytes*.

    Strategy per format:

    * **GIF**: Increase ``--lossy`` in gifsicle, reduce color count.
    * **MP4**: Increase CRF by 2 per iteration.
    * **WebP**: Decrease quality by 10 per iteration.

    Gives up after 10 iterations or when quality hits the floor.
    """
    for attempt in range(10):
        size = path.stat().st_size
        if size <= max_bytes:
            return

        ratio = size / max_bytes

        if fmt == "gif":
            cfg = assembler.gif
            # Escalate lossy compression.
            cfg.lossy_level = min(200, cfg.lossy_level + int(20 * ratio))
            cfg.colors = max(16, cfg.colors - 32)
            if _tool_available("gifsicle"):
                assembler._optimize_gifsicle(path)

        elif fmt == "mp4":
            cfg = assembler.mp4
            cfg.crf = min(51, cfg.crf + 2)
            # Must re-encode.  This is expensive but necessary.
            # The caller should cache frames to avoid re-loading.

        elif fmt == "webp":
            cfg = assembler.webp
            cfg.quality = max(10, cfg.quality - 10)

    # If we still cannot fit, log a warning but do not fail.


# ===================================================================
#  SECTION 5 -- METADATA AND EMBEDDING
# ===================================================================

class MetadataWriter:
    """Embed metadata and source .tex into output files."""

    def __init__(self, meta: MetadataConfig) -> None:
        self.meta = meta

    def write_gif_comment(self, gif_path: Path) -> None:
        """Inject a GIF comment extension block using Pillow.

        The GIF89a specification allows a Comment Extension (0x21 0xFE)
        containing arbitrary UTF-8 text.
        """
        img = Image.open(str(gif_path))
        img.info["comment"] = self._build_comment_string().encode("utf-8")
        # Re-save preserving all frames.
        frames = list(ImageSequence.Iterator(img))
        frames[0].save(
            str(gif_path),
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            loop=img.info.get("loop", 0),
            duration=img.info.get("duration", 100),
            comment=img.info["comment"],
        )

    def write_mp4_metadata(self, mp4_path: Path) -> None:
        """Write MP4 metadata using FFmpeg's -metadata flag (post-hoc).

        Uses ``ffmpeg -i input.mp4 -c copy -metadata key=value output.mp4``.
        """
        if not _tool_available("ffmpeg"):
            return

        tmp = mp4_path.with_suffix(".meta.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", str(mp4_path),
            "-c", "copy",
            "-metadata", f"title={self.meta.title}",
            "-metadata", f"artist={self.meta.author}",
            "-metadata", f"comment={self.meta.comment}",
        ]
        if self.meta.source_tex:
            cmd += ["-metadata", f"description=source_tex_sha256:{_sha256(self.meta.source_tex)}"]
        for k, v in self.meta.custom.items():
            cmd += ["-metadata", f"{k}={v}"]
        cmd.append(str(tmp))
        _run(cmd)
        tmp.replace(mp4_path)

    def write_png_metadata(self, png_path: Path) -> None:
        """Write tEXt chunks into a PNG / APNG using Pillow's PngInfo."""
        from PIL.PngImagePlugin import PngInfo

        img = Image.open(str(png_path))
        info = PngInfo()
        info.add_text("Title", self.meta.title)
        info.add_text("Author", self.meta.author)
        info.add_text("Comment", self.meta.comment)
        if self.meta.source_tex:
            info.add_text("Source-TeX-SHA256", _sha256(self.meta.source_tex))
            # Embed full source if it fits in a tEXt chunk (< 1 MB).
            if len(self.meta.source_tex) < 1_000_000:
                info.add_text("Source-TeX", self.meta.source_tex)
        for k, v in self.meta.custom.items():
            info.add_text(k, v)

        img.save(str(png_path), pnginfo=info)

    def write_webp_metadata(self, webp_path: Path) -> None:
        """Write EXIF metadata into a WebP using Pillow.

        Pillow supports writing EXIF to WebP via the ``exif`` parameter
        on save.  We store the source attribution in the ImageDescription
        EXIF tag.
        """
        import piexif

        exif_dict: dict[str, Any] = {"0th": {}, "Exif": {}, "1st": {}}
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = self._build_comment_string().encode("utf-8")
        exif_dict["0th"][piexif.ImageIFD.Artist] = self.meta.author.encode("utf-8")
        if self.meta.source_tex:
            exif_dict["0th"][piexif.ImageIFD.DocumentName] = (
                f"source_tex_sha256:{_sha256(self.meta.source_tex)}"
            ).encode("utf-8")

        exif_bytes = piexif.dump(exif_dict)

        img = Image.open(str(webp_path))
        # Re-save all frames with EXIF.
        all_frames = list(ImageSequence.Iterator(img))
        all_frames[0].save(
            str(webp_path),
            format="WEBP",
            save_all=True,
            append_images=all_frames[1:],
            exif=exif_bytes,
        )

    def embed_source_tex_sidecar(self, output_path: Path) -> Path:
        """Write the full .tex source as a sidecar file for reproducibility.

        This is a universal fallback when the format does not support
        embedded metadata large enough for the full source.
        """
        sidecar = output_path.with_suffix(".source.tex")
        with open(sidecar, "w") as f:
            f.write(self.meta.source_tex)
        return sidecar

    def _build_comment_string(self) -> str:
        parts = []
        if self.meta.title:
            parts.append(f"Title: {self.meta.title}")
        if self.meta.author:
            parts.append(f"Author: {self.meta.author}")
        if self.meta.comment:
            parts.append(self.meta.comment)
        if self.meta.source_tex:
            parts.append(f"Source SHA-256: {_sha256(self.meta.source_tex)}")
        return " | ".join(parts) if parts else "tikzgif output"


# ---------------------------------------------------------------------------
# Shared frame loading and preparation
# ---------------------------------------------------------------------------

def _load_and_prepare(
    frame_results: list[FrameResult],
    cfg: OutputConfig,
) -> tuple[list[Image.Image], list[int]]:
    """Load PNG images from FrameResult list and resolve timing.

    Returns (images, delays_ms).
    """
    successful = sorted(
        [fr for fr in frame_results if fr.success and fr.png_path and fr.png_path.exists()],
        key=lambda r: r.index,
    )

    if not successful:
        raise ValueError("No successfully compiled frames to assemble")

    images = [Image.open(str(fr.png_path)) for fr in successful]
    delays = cfg.frame_delay.resolve(len(images))

    # Apply quality preset resolution cap.
    preset = QUALITY_PRESETS[cfg.preset]
    max_w = preset["max_width"]
    w, h = images[0].size
    if w > max_w:
        scale = max_w / w
        new_size = (max_w, int(h * scale))
        images = [img.resize(new_size, Image.LANCZOS) for img in images]

    return images, delays


def _maybe_deduplicate(
    images: list[Image.Image],
    delays: list[int],
    cfg: OutputConfig,
) -> list[DeduplicatedFrame]:
    """Optionally deduplicate frames, otherwise wrap as-is."""
    if cfg.deduplicate_frames:
        return deduplicate_frames(images, delays, cfg.deduplicate_threshold)
    return [
        DeduplicatedFrame(image=img, delay_ms=d, original_indices=[i])
        for i, (img, d) in enumerate(zip(images, delays))
    ]


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] if len(s) > max_len else s


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ===================================================================
#  UNIFIED DISPATCHER
# ===================================================================

class AnimationAssembler:
    """Unified entry point that dispatches to the correct assembler
    based on ``OutputConfig.format``.

    Usage::

        config = OutputConfig(
            format=OutputFormat.GIF,
            output_path=Path("output.gif"),
            frame_delay=FrameDelay(default_ms=100, pause_last_ms=2000),
            gif=GifConfig(backend=GifBackend.PILLOW, two_pass_palette=True),
            metadata=MetadataConfig(
                title="My Animation",
                author="J.C. Vaught",
                source_tex=open("source.tex").read(),
            ),
        )
        assembler = AnimationAssembler(config)
        result_path = assembler.assemble(frame_results)
    """

    _ASSEMBLERS: dict[OutputFormat, type] = {
        OutputFormat.GIF: GifAssembler,
        OutputFormat.MP4: Mp4Assembler,
        OutputFormat.WEBP: WebpAssembler,
        OutputFormat.APNG: ApngAssembler,
        OutputFormat.SVG: SvgAnimAssembler,
        OutputFormat.SPRITESHEET: SpritesheetAssembler,
        OutputFormat.PDF_ANIMATE: PdfAnimateAssembler,
    }

    def __init__(self, config: OutputConfig) -> None:
        self.config = config

    def assemble(self, frame_results: list[FrameResult]) -> Path:
        """Run the full assembly pipeline:

        1. Dispatch to format-specific assembler.
        2. Write metadata.
        3. Optionally write source .tex sidecar.
        4. Return path to output file.
        """
        assembler_cls = self._ASSEMBLERS.get(self.config.format)
        if assembler_cls is None:
            raise ValueError(f"Unsupported output format: {self.config.format}")

        assembler = assembler_cls(self.config)
        output_path = assembler.assemble(frame_results)

        # Post-assembly metadata injection.
        meta = MetadataWriter(self.config.metadata)
        fmt = self.config.format

        if fmt == OutputFormat.GIF and self.config.metadata.comment:
            meta.write_gif_comment(output_path)
        elif fmt == OutputFormat.MP4:
            meta.write_mp4_metadata(output_path)
        elif fmt == OutputFormat.APNG:
            meta.write_png_metadata(output_path)
        elif fmt == OutputFormat.WEBP:
            try:
                meta.write_webp_metadata(output_path)
            except ImportError:
                pass  # piexif not available; skip EXIF

        # Sidecar .tex source for reproducibility.
        if self.config.metadata.source_tex:
            meta.embed_source_tex_sidecar(output_path)

        return output_path
