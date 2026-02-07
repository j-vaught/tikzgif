"""
Image post-processing pipeline.

Transforms raw PDF-extracted frames into animation-ready images:
    1. Trim/autocrop whitespace
    2. Normalize to uniform dimensions
    3. Apply background color / transparency
    4. Optional smoothing
    5. Color quantization for GIF (256-color palette)
    6. Frame deduplication
"""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageFilter

logger = logging.getLogger(__name__)


class PadMode(Enum):
    CENTER = auto()
    TOP_LEFT = auto()
    NONE = auto()


class CropMode(Enum):
    CENTER = auto()
    TOP_LEFT = auto()
    NONE = auto()


@dataclass(frozen=True)
class ProcessingConfig:
    trim: bool = True
    trim_fuzz: int = 10
    trim_margin: int = 8
    target_width: Optional[int] = None
    target_height: Optional[int] = None
    pad_mode: PadMode = PadMode.CENTER
    crop_mode: CropMode = CropMode.CENTER
    background_color: str = "white"
    transparent: bool = False
    smooth: bool = False
    smooth_radius: float = 0.5
    quantize: bool = False
    max_colors: int = 256
    dither: bool = True
    deduplicate: bool = True
    dedup_threshold: int = 0
    workers: int = 4


def trim_whitespace(img, fuzz=10, margin=8, background_color="white"):
    """Remove border matching *background_color* within *fuzz* tolerance."""
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, background_color)
    diff = ImageChops.difference(rgba, bg)
    channels = diff.split()
    max_diff = channels[0]
    for ch in channels[1:3]:
        max_diff = ImageChops.lighter(max_diff, ch)
    threshold = max_diff.point(lambda p: 255 if p > fuzz else 0)
    bbox = threshold.getbbox()
    if bbox is None:
        return Image.new("RGBA", (1, 1), background_color)
    left = max(0, bbox[0] - margin)
    upper = max(0, bbox[1] - margin)
    right = min(rgba.width, bbox[2] + margin)
    lower = min(rgba.height, bbox[3] + margin)
    return rgba.crop((left, upper, right, lower))


def normalize_dimensions(img, target_width, target_height,
                         pad_mode=PadMode.CENTER, crop_mode=CropMode.CENTER,
                         background_color="white"):
    """Pad or crop *img* to exactly (target_width, target_height)."""
    w, h = img.size
    if w > target_width or h > target_height:
        if crop_mode == CropMode.CENTER:
            left = max(0, (w - target_width) // 2)
            upper = max(0, (h - target_height) // 2)
        else:
            left, upper = 0, 0
        right = left + min(w, target_width)
        lower = upper + min(h, target_height)
        img = img.crop((left, upper, right, lower))
        w, h = img.size
    if w < target_width or h < target_height:
        canvas = Image.new("RGBA", (target_width, target_height), background_color)
        if pad_mode == PadMode.CENTER:
            paste_x = (target_width - w) // 2
            paste_y = (target_height - h) // 2
        elif pad_mode == PadMode.TOP_LEFT:
            paste_x, paste_y = 0, 0
        else:
            paste_x, paste_y = 0, 0
        canvas.paste(img, (paste_x, paste_y))
        return canvas
    return img


def apply_background(img, color="white", transparent=False):
    if transparent:
        return img.convert("RGBA")
    bg = Image.new("RGBA", img.size, color)
    bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
    return bg


def smooth_frame(img, radius=0.5):
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def quantize_for_gif(img, max_colors=256, dither=True):
    method = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    if img.mode == "RGBA":
        alpha = img.split()[3]
        rgb = img.convert("RGB")
        q = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=method)
        q_rgba = q.convert("RGBA")
        q_rgba.putalpha(alpha)
        return q_rgba
    rgb = img.convert("RGB")
    return rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=method)


def frame_hash(img):
    return hashlib.blake2b(img.tobytes(), digest_size=16).hexdigest()


def frames_are_identical(a, b, threshold=0):
    if a.size != b.size:
        return False
    if threshold == 0:
        return a.tobytes() == b.tobytes()
    diff = ImageChops.difference(a, b)
    extrema = diff.getextrema()
    return max(ch_max for _, ch_max in extrema) <= threshold


def _process_single_frame(img_bytes, img_size, img_mode, config,
                          target_width, target_height):
    img = Image.frombytes(img_mode, img_size, img_bytes)
    if config.trim:
        img = trim_whitespace(img, fuzz=config.trim_fuzz,
                              margin=config.trim_margin,
                              background_color=config.background_color)
    img = normalize_dimensions(img, target_width, target_height,
                               pad_mode=config.pad_mode,
                               crop_mode=config.crop_mode,
                               background_color=config.background_color)
    img = apply_background(img, color=config.background_color,
                           transparent=config.transparent)
    if config.smooth:
        img = smooth_frame(img, radius=config.smooth_radius)
    if config.quantize:
        img = quantize_for_gif(img, max_colors=config.max_colors,
                               dither=config.dither)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
    return (img.tobytes(), img.size, img.mode)


@dataclass
class ProcessingResult:
    frames: List[Image.Image]
    original_count: int
    deduped_count: int
    dimensions: Tuple[int, int]
    warnings: List[str] = field(default_factory=list)


def process_frames(raw_frames, config=ProcessingConfig()):
    warnings = []
    original_count = len(raw_frames)
    if original_count == 0:
        raise ValueError("No frames to process.")

    target_w = config.target_width
    target_h = config.target_height
    if target_w is None or target_h is None:
        max_w, max_h = 0, 0
        for img in raw_frames:
            if config.trim:
                t = trim_whitespace(img, fuzz=config.trim_fuzz,
                                    margin=config.trim_margin,
                                    background_color=config.background_color)
                max_w = max(max_w, t.width)
                max_h = max(max_h, t.height)
            else:
                max_w = max(max_w, img.width)
                max_h = max(max_h, img.height)
        target_w = target_w or max_w
        target_h = target_h or max_h

    valid_frames = []
    for i, img in enumerate(raw_frames):
        if img is None:
            warnings.append(f"Frame {i}: is None (corrupt/missing).")
            continue
        if img.size[0] == 0 or img.size[1] == 0:
            warnings.append(f"Frame {i}: has zero dimension {img.size}.")
            continue
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        valid_frames.append(img)

    if not valid_frames:
        raise ValueError("All frames are corrupt or empty after validation.")

    use_parallel = config.workers > 1 and len(valid_frames) > 4
    if use_parallel:
        processed = _process_parallel(valid_frames, config, target_w, target_h)
    else:
        processed = _process_sequential(valid_frames, config, target_w, target_h)

    deduped_count = 0
    if config.deduplicate and len(processed) > 1:
        deduped = [processed[0]]
        for i in range(1, len(processed)):
            if frames_are_identical(processed[i-1], processed[i],
                                    threshold=config.dedup_threshold):
                deduped_count += 1
            else:
                deduped.append(processed[i])
        processed = deduped

    return ProcessingResult(frames=processed, original_count=original_count,
                            deduped_count=deduped_count,
                            dimensions=(target_w, target_h), warnings=warnings)


def _process_sequential(frames, config, target_w, target_h):
    results = []
    for img in frames:
        raw_bytes, size, mode = _process_single_frame(
            img.tobytes(), img.size, img.mode, config, target_w, target_h)
        results.append(Image.frombytes(mode, size, raw_bytes))
    return results


def _process_parallel(frames, config, target_w, target_h):
    frame_data = [(img.tobytes(), img.size, img.mode) for img in frames]
    results_indexed = []
    with ProcessPoolExecutor(max_workers=config.workers) as pool:
        futures = {
            pool.submit(_process_single_frame, d[0], d[1], d[2],
                        config, target_w, target_h): idx
            for idx, d in enumerate(frame_data)
        }
        for future in as_completed(futures):
            idx = futures[future]
            raw_bytes, size, mode = future.result()
            results_indexed.append((idx, raw_bytes, size, mode))
    results_indexed.sort(key=lambda x: x[0])
    return [Image.frombytes(mode, size, raw_bytes)
            for _, raw_bytes, size, mode in results_indexed]


def stream_process_frames(raw_frames, output_dir, config=ProcessingConfig()):
    """Process frames writing each to disk immediately to save memory."""
    from pathlib import Path as _Path
    output_dir = _Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    warnings = []
    original_count = len(raw_frames)

    target_w = config.target_width
    target_h = config.target_height
    if target_w is None or target_h is None:
        max_w, max_h = 0, 0
        for img in raw_frames:
            if config.trim:
                t = trim_whitespace(img, fuzz=config.trim_fuzz,
                                    margin=config.trim_margin,
                                    background_color=config.background_color)
                max_w = max(max_w, t.width)
                max_h = max(max_h, t.height)
            else:
                max_w = max(max_w, img.width)
                max_h = max(max_h, img.height)
        target_w = target_w or max_w
        target_h = target_h or max_h

    deduped_count = 0
    prev_hash = None
    frame_idx = 0
    for i, img in enumerate(raw_frames):
        if img is None or img.size[0] == 0 or img.size[1] == 0:
            warnings.append(f"Frame {i}: corrupt or empty, skipped.")
            continue
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        raw_bytes, size, mode = _process_single_frame(
            img.tobytes(), img.size, img.mode, config, target_w, target_h)
        processed = Image.frombytes(mode, size, raw_bytes)
        if config.deduplicate:
            h = frame_hash(processed)
            if h == prev_hash:
                deduped_count += 1
                continue
            prev_hash = h
        out_path = output_dir / f"frame_{frame_idx:05d}.png"
        processed.save(out_path, format="PNG", optimize=False)
        frame_idx += 1
        del processed

    return ProcessingResult(frames=[], original_count=original_count,
                            deduped_count=deduped_count,
                            dimensions=(target_w, target_h), warnings=warnings)
