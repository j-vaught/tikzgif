"""
Frame ordering, validation, and the top-level extraction pipeline.

    PDF  -->  [Backend]  -->  raw frames  -->  [Processing]  -->  final frames

Performance targets (pdftoppm, 4-core, SSD):
    100 frames @ 150 DPI:  < 4 s
    100 frames @ 300 DPI:  < 8 s
    100 frames @ 600 DPI:  < 25 s
"""

from __future__ import annotations

import logging
import os
import platform
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from tikzgif.backends import ConversionBackend, RenderConfig
from tikzgif.detection import select_backend
from tikzgif.processing import (ProcessingConfig, ProcessingResult,
                                 process_frames, stream_process_frames)

logger = logging.getLogger(__name__)


@dataclass
class FrameMap:
    page_to_frame: Dict[int, int]
    frame_to_page: Dict[int, int]
    total_pdf_pages: int
    total_frames: int

    @staticmethod
    def identity(n_pages):
        p2f = {i: i for i in range(n_pages)}
        return FrameMap(page_to_frame=p2f, frame_to_page=dict(p2f),
                        total_pdf_pages=n_pages, total_frames=n_pages)

    @staticmethod
    def from_page_list(pages, total_pdf_pages):
        p2f = {page: frame for frame, page in enumerate(pages)}
        f2p = {frame: page for frame, page in enumerate(pages)}
        return FrameMap(page_to_frame=p2f, frame_to_page=f2p,
                        total_pdf_pages=total_pdf_pages, total_frames=len(pages))

    @staticmethod
    def from_range(start, stop, step=1, total_pdf_pages=0):
        pages = list(range(start, stop, step))
        return FrameMap.from_page_list(pages, total_pdf_pages or stop)


@dataclass
class FrameValidation:
    valid: bool
    total_frames: int
    corrupt_indices: List[int] = field(default_factory=list)
    empty_indices: List[int] = field(default_factory=list)
    dimension_mismatches: List[Tuple[int, Tuple[int, int]]] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


def validate_frames(frames, expected_size=None):
    result = FrameValidation(valid=True, total_frames=len(frames))
    if not frames:
        result.valid = False
        result.messages.append("Frame list is empty.")
        return result
    if expected_size is None:
        expected_size = frames[0].size
    for i, frame in enumerate(frames):
        if frame is None:
            result.corrupt_indices.append(i)
            result.messages.append(f"Frame {i}: is None.")
            continue
        if frame.size[0] == 0 or frame.size[1] == 0:
            result.empty_indices.append(i)
            result.messages.append(f"Frame {i}: zero dimension {frame.size}.")
            continue
        if frame.size != expected_size:
            result.dimension_mismatches.append((i, frame.size))
            result.messages.append(
                f"Frame {i}: size {frame.size} != expected {expected_size}.")
        extrema = frame.getextrema()
        if all(mn == mx for mn, mx in extrema):
            result.empty_indices.append(i)
            result.messages.append(
                f"Frame {i}: all pixels identical (solid colour) -- likely corrupt.")
    if result.corrupt_indices or result.empty_indices or result.dimension_mismatches:
        result.valid = False
    return result


@dataclass
class PerfStats:
    backend_name: str
    total_frames: int
    conversion_time_s: float
    processing_time_s: float
    total_time_s: float
    peak_memory_mb: float
    fps_conversion: float
    fps_processing: float
    fps_total: float

    def summary(self):
        return (f"Backend: {self.backend_name}\n"
                f"Frames: {self.total_frames}\n"
                f"Conversion: {self.conversion_time_s:.2f}s "
                f"({self.fps_conversion:.1f} fps)\n"
                f"Processing: {self.processing_time_s:.2f}s "
                f"({self.fps_processing:.1f} fps)\n"
                f"Total: {self.total_time_s:.2f}s "
                f"({self.fps_total:.1f} fps)\n"
                f"Peak memory: {self.peak_memory_mb:.1f} MB")


def _get_peak_memory_mb():
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if platform.system() == "Darwin":
            return usage / (1024 * 1024)
        return usage / 1024
    except Exception:
        return 0.0


def _estimate_frame_memory_mb(width_px, height_px):
    return (width_px * height_px * 4) / (1024 * 1024)


def _compute_batch_size(n_frames, dpi, page_width_pt=612,
                        page_height_pt=792, max_memory_mb=2048):
    px_w = int(page_width_pt * dpi / 72)
    px_h = int(page_height_pt * dpi / 72)
    per_frame_mb = _estimate_frame_memory_mb(px_w, px_h) * 3
    if per_frame_mb <= 0:
        return n_frames
    batch = max(1, int(max_memory_mb / per_frame_mb))
    return min(batch, n_frames)


def _find_fast_tmpdir():
    for candidate in (Path("/dev/shm"), Path("/tmp")):
        if candidate.is_dir() and os.access(candidate, os.W_OK):
            return candidate
    import tempfile
    return Path(tempfile.gettempdir())


@dataclass
class ExtractionResult:
    frames: List[Image.Image]
    frame_map: FrameMap
    validation: FrameValidation
    processing: ProcessingResult
    perf: PerfStats


def extract_frames(pdf_path, render_config=RenderConfig(),
                   processing_config=ProcessingConfig(),
                   pages=None, backend_name=None, max_memory_mb=2048):
    """End-to-end: PDF --> validated, processed animation frames."""
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    t_start = time.perf_counter()
    backend = select_backend(preferred=backend_name)

    total_pages = _count_pdf_pages(pdf_path)
    if pages is not None:
        frame_map = FrameMap.from_page_list(list(pages), total_pages)
    else:
        frame_map = FrameMap.identity(total_pages)
        pages = None

    batch_size = _compute_batch_size(frame_map.total_frames, render_config.dpi,
                                     max_memory_mb=max_memory_mb)

    t_conv = time.perf_counter()
    page_list = sorted(frame_map.frame_to_page.values()) if pages is not None else None

    if batch_size >= frame_map.total_frames or page_list is None:
        raw_frames = backend.convert(pdf_path, render_config, page_list)
    else:
        raw_frames = []
        for bs in range(0, len(page_list), batch_size):
            bp = page_list[bs:bs + batch_size]
            raw_frames.extend(backend.convert(pdf_path, render_config, bp))

    conversion_time = time.perf_counter() - t_conv

    t_proc = time.perf_counter()
    estimated_mb = (_estimate_frame_memory_mb(
        raw_frames[0].width if raw_frames else 1,
        raw_frames[0].height if raw_frames else 1) * len(raw_frames) * 2)

    if estimated_mb > max_memory_mb:
        fast_tmp = _find_fast_tmpdir()
        output_dir = fast_tmp / f"tikzgif_frames_{os.getpid()}"
        proc_result = stream_process_frames(raw_frames, output_dir, processing_config)
        frame_files = sorted(output_dir.glob("frame_*.png"))
        final_frames = []
        for fp in frame_files:
            img = Image.open(fp)
            img.load()
            final_frames.append(img)
        proc_result = ProcessingResult(
            frames=final_frames, original_count=proc_result.original_count,
            deduped_count=proc_result.deduped_count,
            dimensions=proc_result.dimensions, warnings=proc_result.warnings)
    else:
        proc_result = process_frames(raw_frames, processing_config)

    processing_time = time.perf_counter() - t_proc

    validation = validate_frames(proc_result.frames,
                                 expected_size=proc_result.dimensions)

    total_time = time.perf_counter() - t_start
    n = len(proc_result.frames) or 1

    perf = PerfStats(
        backend_name=backend.name, total_frames=len(proc_result.frames),
        conversion_time_s=conversion_time, processing_time_s=processing_time,
        total_time_s=total_time, peak_memory_mb=_get_peak_memory_mb(),
        fps_conversion=len(raw_frames) / max(conversion_time, 0.001),
        fps_processing=n / max(processing_time, 0.001),
        fps_total=n / max(total_time, 0.001))

    return ExtractionResult(frames=proc_result.frames, frame_map=frame_map,
                            validation=validation, processing=proc_result, perf=perf)


def _count_pdf_pages(pdf_path):
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except ImportError:
        pass
    import shutil, subprocess
    if shutil.which("pdfinfo"):
        try:
            result = subprocess.run(["pdfinfo", str(pdf_path)],
                                    capture_output=True, timeout=10)
            for line in result.stdout.decode().split("\n"):
                if line.startswith("Pages:"):
                    return int(line.split(":")[1].strip())
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
    for gs_name in ("gs", "gswin64c", "gswin32c"):
        if shutil.which(gs_name):
            try:
                result = subprocess.run(
                    [gs_name, "-q", "-dNODISPLAY", "-dNOSAFER", "-c",
                     f"({pdf_path}) (r) file runpdfbegin pdfpagecount = quit"],
                    capture_output=True, timeout=10)
                return int(result.stdout.decode().strip())
            except (subprocess.TimeoutExpired, ValueError, OSError):
                pass
    return 0
