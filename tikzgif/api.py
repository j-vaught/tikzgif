"""Public library API for rendering parameterized TikZ animations."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .assembly import (
    AnimationAssembler,
    FrameDelay,
    OutputConfig,
    OutputFormat,
    QualityPreset,
)
from .backends import PdftoppmBackend, RenderConfig
from .compiler import compile_with_bbox_normalization
from .types import CompilationConfig, ErrorPolicy, LatexEngine

_FORMAT_MAP = {
    "gif": OutputFormat.GIF,
    "mp4": OutputFormat.MP4,
}

_QUALITY_MAP = {
    "web": QualityPreset.WEB,
    "presentation": QualityPreset.PRESENTATION,
    "print": QualityPreset.PRINT,
}

_ENGINE_MAP = {
    "pdflatex": LatexEngine.PDFLATEX,
    "xelatex": LatexEngine.XELATEX,
    "lualatex": LatexEngine.LUALATEX,
}

_POLICY_MAP = {
    "abort": ErrorPolicy.ABORT,
    "skip": ErrorPolicy.SKIP,
    "retry": ErrorPolicy.RETRY,
}


@dataclass
class RenderResult:
    output_path: Path
    total_frames: int
    successful_frames: int
    failed_frames: int
    size_bytes: int


def render(
    tex_file: str | Path,
    *,
    param: str = "PARAM",
    start: float = 0.0,
    end: float = 1.0,
    frames: int = 30,
    fps: int = 10,
    format: str = "gif",
    quality: str = "presentation",
    engine: str | None = None,
    workers: int = 0,
    timeout: float = 30.0,
    dpi: int = 300,
    error_policy: str = "retry",
    output: str | Path | None = None,
    raw_pdf_dir: str | Path | None = None,
    raw_png_dir: str | Path | None = None,
) -> RenderResult:
    """Render a parameterized .tex file to GIF or MP4.

    This is the public API used by both library callers and CLI.
    """
    tex_path = Path(tex_file)
    if not tex_path.is_file():
        raise FileNotFoundError(f"file not found: {tex_path}")

    if format not in _FORMAT_MAP:
        raise ValueError(f"Unsupported format '{format}'. Use 'gif' or 'mp4'.")

    if quality not in _QUALITY_MAP:
        raise ValueError(
            f"Unsupported quality '{quality}'. Use one of: {', '.join(_QUALITY_MAP)}."
        )

    if error_policy not in _POLICY_MAP:
        raise ValueError(
            "Unsupported error_policy "
            f"'{error_policy}'. Use one of: {', '.join(_POLICY_MAP)}."
        )

    if frames <= 0:
        raise ValueError("frames must be >= 1")

    source = tex_path.read_text(encoding="utf-8")

    if frames == 1:
        param_values = [start]
    else:
        param_values = [start + i * (end - start) / (frames - 1) for i in range(frames)]

    latex_engine = _ENGINE_MAP.get(engine) if engine else None
    comp_config = CompilationConfig(
        engine=latex_engine,
        error_policy=_POLICY_MAP[error_policy],
        max_workers=workers,
        timeout_per_frame_s=timeout,
        dpi=dpi,
    )

    frame_results, _envelope = compile_with_bbox_normalization(
        source,
        param_values,
        comp_config,
        param_token="\\" + param,
    )

    successful = [r for r in frame_results if r.success]
    failed = [r for r in frame_results if not r.success]

    if not successful:
        details = "\n".join(
            f"Frame {r.index}: {r.error_message}" for r in failed[:5]
        )
        raise RuntimeError(f"All frames failed to compile.\n{details}")

    if not PdftoppmBackend.is_available():
        raise RuntimeError(
            "pdftoppm not found. Install poppler-utils "
            "(macOS: brew install poppler)."
        )

    backend = PdftoppmBackend()
    render_config = RenderConfig(dpi=dpi, antialias=False, threads=1)

    pdf_dir = Path(raw_pdf_dir) if raw_pdf_dir else None
    png_dir = Path(raw_png_dir) if raw_png_dir else None
    if pdf_dir:
        pdf_dir.mkdir(parents=True, exist_ok=True)
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tikzgif_render_") as tmpdir:
        tmp = Path(tmpdir)
        for result in successful:
            if not result.pdf_path or not result.pdf_path.exists():
                continue

            if pdf_dir is not None:
                shutil.copy2(result.pdf_path, pdf_dir / f"frame_{result.index:06d}.pdf")

            images = backend.convert(result.pdf_path, render_config)
            if images:
                png_path = tmp / f"frame_{result.index:06d}.png"
                images[0].save(str(png_path), format="PNG")
                result.png_path = png_path
                if png_dir is not None:
                    shutil.copy2(png_path, png_dir / f"frame_{result.index:06d}.png")

        output_path = Path(output) if output else Path(tex_path.stem + f".{format}")

        delay_ms = int(1000 / fps) if fps > 0 else 100
        output_config = OutputConfig(
            format=_FORMAT_MAP[format],
            output_path=output_path,
            preset=_QUALITY_MAP[quality],
            frame_delay=FrameDelay(default_ms=delay_ms),
        )
        output_config.mp4.fps = float(fps)

        result_path = AnimationAssembler(output_config).assemble(frame_results)

    size_bytes = result_path.stat().st_size
    return RenderResult(
        output_path=result_path,
        total_frames=frames,
        successful_frames=len(successful),
        failed_frames=len(failed),
        size_bytes=size_bytes,
    )
