"""Public library API for rendering parameterized TikZ animations."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .assembly import AnimationAssembler
from .backends import PdftoppmBackend
from .compiler import compile_single_pass
from .config import RenderJobConfig, legacy_args_to_job_config


@dataclass
class RenderResult:
    output_path: Path
    total_frames: int
    successful_frames: int
    failed_frames: int
    size_bytes: int


def render_job(job: RenderJobConfig) -> RenderResult:
    """Render a job described by explicit stage-level config objects."""
    tex_path = Path(job.tex_file)
    if not tex_path.is_file():
        raise FileNotFoundError(f"file not found: {tex_path}")

    source = tex_path.read_text(encoding="utf-8")
    param_values = job.param_values()

    frame_results = compile_single_pass(
        source,
        param_values,
        job.compile.to_compilation_config(),
        param_token=job.template.param_token,
        extra_preamble=job.template.extra_preamble,
        enforced_bbox=job.template.enforced_bbox,
    )

    successful = [r for r in frame_results if r.success]
    failed = [r for r in frame_results if not r.success]

    if not successful:
        details = "\n".join(f"Frame {r.index}: {r.error_message}" for r in failed[:5])
        raise RuntimeError(f"All frames failed to compile.\n{details}")

    # PR1 keeps behavior unchanged by continuing to use pdftoppm only.
    # Backend selection wiring is introduced in a later refactor phase.
    if not PdftoppmBackend.is_available():
        raise RuntimeError(
            "pdftoppm not found. Install poppler-utils "
            "(macOS: brew install poppler)."
        )

    backend = PdftoppmBackend()
    render_config = job.raster.to_render_config()

    pdf_dir = job.output.raw_pdf_dir
    png_dir = job.output.raw_png_dir
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

        default_output_path = Path(tex_path.stem + f".{job.output.format.value}")
        output_config = job.output.to_assembly_config(default_output_path)
        result_path = AnimationAssembler(output_config).assemble(frame_results)

    size_bytes = result_path.stat().st_size
    return RenderResult(
        output_path=result_path,
        total_frames=job.frames,
        successful_frames=len(successful),
        failed_frames=len(failed),
        size_bytes=size_bytes,
    )


def render(
    tex_file: str | Path,
    *,
    param: str = "PARAM",
    start: float = 0.0,
    end: float = 1.0,
    frames: int = 90,
    fps: int = 30,
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
    bbox: tuple[float, float, float, float] | None = None,
) -> RenderResult:
    """Render a parameterized .tex file to GIF or MP4.

    This is the public backward-compatible API used by CLI and library callers.
    """
    job = legacy_args_to_job_config(
        tex_file,
        param=param,
        start=start,
        end=end,
        frames=frames,
        fps=fps,
        format=format,
        quality=quality,
        engine=engine,
        workers=workers,
        timeout=timeout,
        dpi=dpi,
        error_policy=error_policy,
        output=output,
        raw_pdf_dir=raw_pdf_dir,
        raw_png_dir=raw_png_dir,
        bbox=bbox,
    )
    return render_job(job)
