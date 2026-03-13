"""Public library API for rendering parameterized TikZ animations."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .assemble import AnimationAssembler
from .compile import compile_single_pass
from .config import RenderJobConfig, legacy_args_to_job_config
from .exceptions import RenderError
from .rasterize import get_backend_by_name


@dataclass
class RenderResult:
    """Result returned by a completed render job.

    Attributes:
        output_path: Path to the generated output file (GIF or MP4).
        total_frames: Total number of frames in the animation.
        successful_frames: Number of frames that compiled successfully.
        failed_frames: Number of frames that failed to compile.
        size_bytes: Size of the output file in bytes.
    """

    output_path: Path
    total_frames: int
    successful_frames: int
    failed_frames: int
    size_bytes: int
    failure_details: list[tuple[int, str]] = field(default_factory=list)


def render_job(job: RenderJobConfig) -> RenderResult:
    """Render a job described by explicit stage-level config objects.

    Executes the full pipeline: template parsing, parallel LaTeX
    compilation, PDF rasterization, and output assembly.

    Args:
        job: Fully specified render job configuration.

    Returns:
        A ``RenderResult`` with output path and frame statistics.

    Raises:
        FileNotFoundError: If the ``.tex`` file does not exist.
        RenderError: If all frames fail to compile.
        tikzgif.exceptions.CompilationError: If compilation fails
            under ``ABORT`` error policy.
        tikzgif.exceptions.ConverterNotFoundError: If the raster
            backend is unavailable.
        tikzgif.exceptions.AssemblyError: If output assembly fails.
    """
    tex_path = Path(job.tex_file)
    if not tex_path.is_file():
        raise FileNotFoundError(f"TeX file not found: {tex_path}")

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
        raise RenderError(
            f"All {len(failed)} frames failed to compile.\n{details}",
            stage="compile",
        )

    backend = get_backend_by_name(job.raster.backend)
    render_config = job.raster.to_render_config()

    pdf_dir = job.output.raw_pdf_dir
    png_dir = job.output.raw_png_dir
    if pdf_dir:
        pdf_dir.mkdir(parents=True, exist_ok=True)
    if png_dir:
        png_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tikzgif_render_") as tmpdir:
        tmp = Path(tmpdir)
        raster_failures: list[tuple[int, str]] = []
        for result in successful[:]:
            if not result.pdf_path or not result.pdf_path.exists():
                continue

            if pdf_dir is not None:
                shutil.copy2(result.pdf_path, pdf_dir / f"frame_{result.index:06d}.pdf")

            try:
                images = backend.convert(result.pdf_path, render_config)
            except Exception as exc:
                result.success = False
                result.error_message = f"Rasterization failed: {exc}"
                successful.remove(result)
                failed.append(result)
                raster_failures.append((result.index, result.error_message))
                continue
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
    failure_details = [
        (r.index, r.error_message) for r in failed
    ]
    return RenderResult(
        output_path=result_path,
        total_frames=job.frames,
        successful_frames=len(successful),
        failed_frames=len(failed),
        size_bytes=size_bytes,
        failure_details=failure_details,
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
    shell_escape: bool = False,
    latex_args: list[str] | tuple[str, ...] | None = None,
    cache_dir: str | Path | None = None,
    backend: str = "pdftoppm",
    color_space: str = "rgba",
    background: str | None = "white",
    antialias: bool = False,
    antialias_factor: int = 2,
    raster_threads: int = 1,
    gif_loop_count: int = 0,
    mp4_crf: int = 23,
    mp4_preset: str = "medium",
    mp4_pixel_format: str = "yuv420p",
    metadata_title: str = "",
    metadata_author: str = "",
    metadata_comment: str = "Generated by tikzgif",
    frame_delay_default_ms: int | None = None,
    pause_first_ms: int | None = None,
    pause_last_ms: int | None = None,
) -> RenderResult:
    """Render a parameterized ``.tex`` file to GIF or MP4.

    This is the primary public API for both CLI and library callers.
    All parameters are converted to a ``RenderJobConfig`` and delegated
    to ``render_job()``.

    Args:
        tex_file: Path to the ``.tex`` template file.
        param: Parameter token name (without the leading backslash).
        start: Starting parameter value.
        end: Ending parameter value.
        frames: Number of animation frames to generate.
        fps: Frames per second in the output.
        format: Output format (``"gif"`` or ``"mp4"``).
        quality: Quality preset (``"web"``, ``"presentation"``, ``"print"``).
        engine: LaTeX engine name, or ``None`` for auto-detection.
        workers: Number of parallel compilation workers (0 = auto).
        timeout: Timeout per frame in seconds.
        dpi: Target DPI for rasterization.
        error_policy: How to handle frame failures
            (``"abort"``, ``"skip"``, ``"retry"``).
        output: Explicit output file path, or ``None`` for auto.
        raw_pdf_dir: Directory to copy raw per-frame PDFs, or ``None``.
        raw_png_dir: Directory to copy raw per-frame PNGs, or ``None``.
        bbox: Fixed bounding box ``(xmin, ymin, xmax, ymax)``, or ``None``.
        shell_escape: Whether to pass ``--shell-escape`` to LaTeX.
        latex_args: Additional arguments forwarded to the LaTeX engine.
        cache_dir: Custom cache directory path, or ``None`` for default.
        backend: Rasterization backend name.
        color_space: Target color space (``"rgb"``, ``"rgba"``, ``"grayscale"``).
        background: Background color name, or ``None`` for transparency.
        antialias: Whether to enable anti-aliasing via supersampling.
        antialias_factor: Supersampling multiplier.
        raster_threads: Number of rasterization threads.
        gif_loop_count: GIF loop count (0 = infinite).
        mp4_crf: MP4 constant rate factor.
        mp4_preset: ffmpeg encoding preset.
        mp4_pixel_format: MP4 pixel format.
        metadata_title: Output file title metadata.
        metadata_author: Output file author metadata.
        metadata_comment: Output file comment metadata.
        frame_delay_default_ms: Default inter-frame delay in ms.
        pause_first_ms: Pause duration on first frame in ms.
        pause_last_ms: Pause duration on last frame in ms.

    Returns:
        A ``RenderResult`` with output path and frame statistics.
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
        shell_escape=shell_escape,
        latex_args=latex_args,
        cache_dir=cache_dir,
        backend=backend,
        color_space=color_space,
        background=background,
        antialias=antialias,
        antialias_factor=antialias_factor,
        raster_threads=raster_threads,
        gif_loop_count=gif_loop_count,
        mp4_crf=mp4_crf,
        mp4_preset=mp4_preset,
        mp4_pixel_format=mp4_pixel_format,
        metadata_title=metadata_title,
        metadata_author=metadata_author,
        metadata_comment=metadata_comment,
        frame_delay_default_ms=frame_delay_default_ms,
        pause_first_ms=pause_first_ms,
        pause_last_ms=pause_last_ms,
    )
    return render_job(job)
