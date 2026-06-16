"""Public library API for rendering parameterized TikZ animations."""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .assemble import AnimationAssembler
from .compile import compile_single_pass, select_engine
from .compile.pipeline import _determine_worker_count
from .config import RenderJobConfig, legacy_args_to_job_config
from .exceptions import ConverterNotFoundError, InputError, RenderError, TikzGifError
from .rasterize import get_backend_by_name
from .template import parse_template_from_file

if TYPE_CHECKING:
    from .rasterize.backends import ConversionBackend, RenderConfig
    from .types import FrameResult


@dataclass
class RenderResult:
    """Result returned by a completed render job.

    Attributes:
        output_path: Path to the generated output file (GIF or MP4).
        total_frames: Total number of frames in the animation.
        successful_frames: Number of frames that compiled successfully.
        failed_frames: Number of frames that failed to compile.
        size_bytes: Size of the output file in bytes.
        failure_details: ``(frame_index, reason)`` pairs for failed frames.
        test_outputs: Preview PNG paths produced in test mode.
        cached_frames: Number of frames served from the compilation cache.
        duration_seconds: Wall-clock time for the whole render, in seconds.
        engine: Requested LaTeX engine name, or ``"auto"`` for auto-detect.
        backend: Rasterization backend name used.
    """

    output_path: Path
    total_frames: int
    successful_frames: int
    failed_frames: int
    size_bytes: int
    failure_details: list[tuple[int, str]] = field(default_factory=list)
    test_outputs: list[Path] = field(default_factory=list)
    cached_frames: int = 0
    duration_seconds: float = 0.0
    engine: str = "auto"
    backend: str = "pdftoppm"


@dataclass
class ValidationCheck:
    """Outcome of a single pre-flight check performed by :func:`validate_render`.

    Attributes:
        name: Short, human-friendly name of the thing being checked
            (e.g. ``"input file"`` or ``"LaTeX engine"``).
        passed: Whether the check succeeded.
        detail: A one-line description of what was found.
        hint: When the check failed, a plain-English suggestion for how to
            fix it; empty when the check passed.
    """

    name: str
    passed: bool
    detail: str = ""
    hint: str = ""


@dataclass
class ValidationReport:
    """Aggregate result of a :func:`validate_render` pre-flight run.

    Attributes:
        ok: ``True`` only when every check passed.
        checks: All checks performed, in the order they were run.
        first_error: The exception behind the first failed check, used to
            choose a process exit code; ``None`` when everything passed.
    """

    ok: bool
    checks: list[ValidationCheck] = field(default_factory=list)
    first_error: Exception | None = None


@dataclass
class _RasterOutcome:
    """Result of rasterizing a single frame in a worker thread.

    Attributes:
        index: Frame index (unique, used for output filenames).
        result: The ``FrameResult`` that was rasterized.
        png_path: Path to the written PNG, or ``None`` if none was produced.
        error_message: Failure message, or ``None`` on success.
        exception: The original exception object caught in the worker, or
            ``None`` on success. Preserves typed attributes (e.g.
            ``ConverterNotFoundError.install_hint``) that the stringified
            ``error_message`` would otherwise lose.
    """

    index: int
    result: FrameResult
    png_path: Path | None
    error_message: str | None
    exception: Exception | None = None


def _rasterize_frame(
    result: FrameResult,
    backend: ConversionBackend,
    render_config: RenderConfig,
    tmp: Path,
    pdf_dir: Path | None,
    png_dir: Path | None,
) -> _RasterOutcome:
    """Rasterize one compiled frame's PDF into a PNG.

    Pure worker: performs the optional PDF copy, the PDF-to-image
    conversion, the PNG save, and the optional PNG copy, then returns an
    outcome describing what happened. It never mutates shared state and
    never prints progress; the caller merges the outcome on the main
    thread. Writing to a per-index filename ``frame_{index:06d}.png`` is
    collision-free because frame indices are unique.

    Args:
        result: Frame result whose ``pdf_path`` is rasterized.
        backend: Rasterization backend (each ``convert`` call is
            self-contained and thread-safe).
        render_config: Backend render settings.
        tmp: Temporary directory the PNG is written into.
        pdf_dir: Directory to copy the raw PDF into, or ``None``.
        png_dir: Directory to copy the PNG into, or ``None``.

    Returns:
        A ``_RasterOutcome`` carrying the index, the result object, the
        written PNG path (or ``None``), and an error message (or ``None``).
    """
    assert result.pdf_path is not None

    if pdf_dir is not None:
        shutil.copy2(result.pdf_path, pdf_dir / f"frame_{result.index:06d}.pdf")

    try:
        images = backend.convert(result.pdf_path, render_config)
    except Exception as exc:
        return _RasterOutcome(
            index=result.index,
            result=result,
            png_path=None,
            error_message=f"Rasterization failed: {exc}",
            exception=exc,
        )

    png_path: Path | None = None
    if images:
        png_path = tmp / f"frame_{result.index:06d}.png"
        images[0].save(str(png_path), format="PNG")
        if png_dir is not None:
            shutil.copy2(png_path, png_dir / f"frame_{result.index:06d}.png")

    return _RasterOutcome(
        index=result.index,
        result=result,
        png_path=png_path,
        error_message=None,
    )


def render_job(job: RenderJobConfig, *, show_progress: bool = True) -> RenderResult:
    """Render a job described by explicit stage-level config objects.

    Executes the full pipeline: template parsing, parallel LaTeX
    compilation, PDF rasterization, and output assembly.

    Args:
        job: Fully specified render job configuration.
        show_progress: Whether to print the per-frame rasterization
            progress counter to stderr. Set ``False`` to silence it
            (e.g. for machine-readable CLI output). Defaults to ``True``
            so library behavior is unchanged.

    Returns:
        A ``RenderResult`` with output path and frame statistics.

    Raises:
        InputError: If the ``.tex`` file does not exist.
        RenderError: If all frames fail to compile.
        tikzgif.exceptions.CompilationError: If compilation fails
            under ``ABORT`` error policy.
        tikzgif.exceptions.ConverterNotFoundError: If the raster
            backend is unavailable.
        tikzgif.exceptions.AssemblyError: If output assembly fails.
    """
    start_time = time.monotonic()
    engine_label = job.compile.engine.value if job.compile.engine else "auto"
    backend_label = job.raster.backend

    tex_path = Path(job.tex_file)
    if not tex_path.is_file():
        raise InputError(f"TeX file not found: {tex_path}")

    source = tex_path.read_text(encoding="utf-8")
    param_values = job.param_values()

    if job.test_mode:
        if len(param_values) >= 2:
            param_values = [param_values[0], param_values[-1]]
        else:
            param_values = [param_values[0]]

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
    cached_frames = sum(1 for r in frame_results if r.cached)

    if not successful:
        details = "\n".join(f"Frame {r.index}: {r.error_message}" for r in failed[:5])
        if len(failed) > 5:
            remaining = len(failed) - 5
            details += f"\n... and {remaining} more failure(s)"
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

        # Frames missing a compiled PDF are skipped (not rasterized) and
        # left untouched in ``successful``, matching the old loop's
        # ``continue``. The progress denominator counts only frames that
        # are actually submitted for rasterization.
        to_rasterize = [r for r in successful if r.pdf_path and r.pdf_path.exists()]
        raster_total = len(to_rasterize)

        # Reuse the compilation worker budget; "auto" (max_workers == 0)
        # resolves the same way compilation does. Cap the pool at the
        # number of frames actually being submitted.
        workers = _determine_worker_count(job.compile.to_compilation_config())
        max_workers = max(1, min(workers, raster_total)) if raster_total else 1

        completed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [
                ex.submit(
                    _rasterize_frame,
                    result,
                    backend,
                    render_config,
                    tmp,
                    pdf_dir,
                    png_dir,
                )
                for result in to_rasterize
            ]

            # Merge every outcome on the main thread, so the shared
            # ``successful`` / ``failed`` / ``raster_failures`` lists are
            # mutated by a single thread and need no locking.
            for fut in as_completed(futures):
                outcome = fut.result()
                completed += 1
                if show_progress:
                    pct = (completed / raster_total) * 100 if raster_total else 100
                    print(
                        f"\rRasterizing: {completed}/{raster_total} ({pct:.0f}%)",
                        end="",
                        flush=True,
                        file=sys.stderr,
                    )

                result = outcome.result
                if outcome.error_message is not None:
                    # A missing converter is environmental: every frame would
                    # fail identically. Re-raise from the main thread so the
                    # typed error (with its install_hint) reaches the CLI and
                    # maps to the missing-dependency exit code. The enclosing
                    # ThreadPoolExecutor context manager shuts the pool down.
                    if isinstance(outcome.exception, ConverterNotFoundError):
                        raise outcome.exception
                    result.success = False
                    result.error_message = outcome.error_message
                    successful.remove(result)
                    failed.append(result)
                    raster_failures.append((outcome.index, outcome.error_message))
                else:
                    result.png_path = outcome.png_path
        if show_progress:
            print(file=sys.stderr)

        if job.test_mode:
            stem = tex_path.stem
            output_paths: list[Path] = []
            for r in successful:
                if r.png_path and r.png_path.exists():
                    label = "first" if r.index == 0 else "last"
                    dest = Path(f"{stem}_test_{label}.png")
                    shutil.copy2(r.png_path, dest)
                    output_paths.append(dest)
            failure_details = [(r.index, r.error_message) for r in failed]
            first_output = (
                output_paths[0] if output_paths else Path(f"{stem}_test_first.png")
            )
            return RenderResult(
                output_path=first_output,
                total_frames=len(param_values),
                successful_frames=len(successful),
                failed_frames=len(failed),
                size_bytes=sum(p.stat().st_size for p in output_paths if p.exists()),
                failure_details=failure_details,
                test_outputs=output_paths,
                cached_frames=cached_frames,
                duration_seconds=time.monotonic() - start_time,
                engine=engine_label,
                backend=backend_label,
            )

        default_output_path = Path(tex_path.stem + f".{job.output.format.value}")
        output_config = job.output.to_assembly_config(default_output_path)
        result_path = AnimationAssembler(output_config).assemble(frame_results)

    size_bytes = result_path.stat().st_size
    failure_details = [(r.index, r.error_message) for r in failed]
    return RenderResult(
        output_path=result_path,
        total_frames=job.frames,
        successful_frames=len(successful),
        failed_frames=len(failed),
        size_bytes=size_bytes,
        failure_details=failure_details,
        cached_frames=cached_frames,
        duration_seconds=time.monotonic() - start_time,
        engine=engine_label,
        backend=backend_label,
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
    no_cache: bool = False,
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
    test_mode: bool = False,
    show_progress: bool = True,
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
        workers: Number of parallel workers for frame compilation and
            rasterization (0 = auto).
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
        test_mode: Render only the first and last frames as preview PNGs.
        show_progress: Whether to print the per-frame rasterization
            progress counter to stderr. Defaults to ``True``.

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
        no_cache=no_cache,
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
        test_mode=test_mode,
    )
    return render_job(job, show_progress=show_progress)


def validate_render(
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
    bbox: tuple[float, float, float, float] | None = None,
    shell_escape: bool = False,
    latex_args: list[str] | tuple[str, ...] | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
    backend: str = "pdftoppm",
    color_space: str = "rgba",
    background: str | None = "white",
    antialias: bool = False,
    antialias_factor: int = 2,
    raster_threads: int = 1,
) -> ValidationReport:
    """Check that a render would succeed, without compiling anything.

    Runs the cheap, fast pre-flight steps a real render would do first.
    The numbers are in range, the input file exists and is readable, the
    options are recognized, the template parses, a LaTeX engine is
    installed, the rasterization backend is available, and the output
    directory can be written to. Every check is attempted so the report
    lists all problems at once rather than stopping at the first.

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
        workers: Number of parallel workers (only carried into the job).
        timeout: Timeout per frame in seconds.
        dpi: Target DPI for rasterization.
        error_policy: How to handle frame failures.
        output: Explicit output file path, or ``None`` for auto.
        bbox: Fixed bounding box ``(xmin, ymin, xmax, ymax)``, or ``None``.
        shell_escape: Whether ``--shell-escape`` would be passed to LaTeX.
        latex_args: Additional arguments forwarded to the LaTeX engine.
        cache_dir: Custom cache directory path, or ``None`` for default.
        no_cache: Whether the cache would be bypassed.
        backend: Rasterization backend name.
        color_space: Target color space.
        background: Background color name, or ``None`` for transparency.
        antialias: Whether anti-aliasing would be enabled.
        antialias_factor: Supersampling multiplier.
        raster_threads: Number of rasterization threads.

    Returns:
        A ``ValidationReport`` whose ``ok`` flag is ``True`` only when every
        check passed. No files are written and no ``RenderResult`` is
        produced.
    """
    checks: list[ValidationCheck] = []
    first_error: Exception | None = None

    def record(exc: Exception) -> None:
        nonlocal first_error
        if first_error is None:
            first_error = exc

    # 1. Numeric arguments are in range.
    numeric_problems: list[str] = []
    if frames < 1:
        numeric_problems.append("frames must be >= 1")
    if fps < 1:
        numeric_problems.append("fps must be >= 1")
    if dpi < 1:
        numeric_problems.append("dpi must be >= 1")
    if timeout <= 0:
        numeric_problems.append("timeout must be greater than 0")
    if not math.isfinite(start) or not math.isfinite(end):
        numeric_problems.append("start and end must be finite numbers")
    if numeric_problems:
        joined = "; ".join(numeric_problems)
        checks.append(
            ValidationCheck(
                "numbers", False, joined, "Pass values in the documented range."
            )
        )
        record(InputError(joined))
    else:
        checks.append(
            ValidationCheck(
                "numbers",
                True,
                f"frames={frames}, fps={fps}, dpi={dpi}, timeout={timeout:g}s",
            )
        )

    # 2. The input file exists and is readable.
    tex_path = Path(tex_file)
    readable = False
    if not tex_path.is_file():
        checks.append(
            ValidationCheck(
                "input file",
                False,
                f"not found: {tex_path}",
                "Check the path and spelling of the .tex file.",
            )
        )
        record(InputError(f"TeX file not found: {tex_path}"))
    elif not os.access(tex_path, os.R_OK):
        checks.append(
            ValidationCheck(
                "input file",
                False,
                f"not readable: {tex_path}",
                "Fix the file permissions so the .tex file can be read.",
            )
        )
        record(InputError(f"TeX file is not readable: {tex_path}"))
    else:
        readable = True
        checks.append(ValidationCheck("input file", True, str(tex_path)))

    # 3. Options translate into a valid job configuration.
    job: RenderJobConfig | None = None
    try:
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
            bbox=bbox,
            shell_escape=shell_escape,
            latex_args=latex_args,
            cache_dir=cache_dir,
            no_cache=no_cache,
            backend=backend,
            color_space=color_space,
            background=background,
            antialias=antialias,
            antialias_factor=antialias_factor,
            raster_threads=raster_threads,
        )
        checks.append(
            ValidationCheck(
                "options",
                True,
                f"format={format}, quality={quality}, error-policy={error_policy}",
            )
        )
    except TikzGifError as exc:
        checks.append(
            ValidationCheck(
                "options",
                False,
                str(exc),
                "Use a documented value for the flagged option.",
            )
        )
        record(exc)

    # 4. The template parses (only meaningful once the file is readable).
    parsed = None
    if readable:
        try:
            parsed = parse_template_from_file(tex_path, param_token="\\" + param)
            checks.append(
                ValidationCheck(
                    "template",
                    True,
                    f"class={parsed.document_class}, "
                    f"packages={len(parsed.detected_packages)}",
                )
            )
        except TikzGifError as exc:
            checks.append(
                ValidationCheck(
                    "template",
                    False,
                    str(exc),
                    "Fix the .tex so it parses (see the message above).",
                )
            )
            record(exc)
    else:
        checks.append(
            ValidationCheck(
                "template",
                False,
                "not checked yet -- the input file must be readable first",
                "Fix the input file above, then run --validate again.",
            )
        )

    # 5. A LaTeX engine is installed for this template.
    preferred = job.compile.engine if job is not None else None
    packages = parsed.detected_packages if parsed is not None else set()
    try:
        selected = select_engine(preferred=preferred, packages=packages)
        checks.append(ValidationCheck("LaTeX engine", True, selected.value))
    except TikzGifError as exc:
        checks.append(
            ValidationCheck(
                "LaTeX engine",
                False,
                str(exc),
                "Install a LaTeX distribution (TeX Live or MiKTeX).",
            )
        )
        record(exc)

    # 6. The rasterization backend is available.
    backend_name = job.raster.backend if job is not None else backend
    try:
        get_backend_by_name(backend_name)
        checks.append(ValidationCheck("raster backend", True, backend_name))
    except TikzGifError as exc:
        hint = getattr(exc, "install_hint", "") or (
            "Choose an available backend (see: tikzgif inspect backends)."
        )
        checks.append(ValidationCheck("raster backend", False, str(exc), hint))
        record(exc)

    # 7. The output directory exists and can be written to.
    if job is not None:
        out_path = job.output.output_path or Path(
            tex_path.stem + f".{job.output.format.value}"
        )
    elif output is not None:
        out_path = Path(output)
    else:
        out_path = Path(tex_path.stem + f".{format}")
    parent = out_path.parent if str(out_path.parent) else Path(".")
    if not parent.exists():
        checks.append(
            ValidationCheck(
                "output location",
                False,
                f"directory does not exist: {parent}",
                "Create the directory, or choose another --output path.",
            )
        )
        record(InputError(f"Output directory does not exist: {parent}"))
    elif not os.access(parent, os.W_OK):
        checks.append(
            ValidationCheck(
                "output location",
                False,
                f"not writable: {parent}",
                "Choose a writable --output location.",
            )
        )
        record(InputError(f"Output directory is not writable: {parent}"))
    else:
        checks.append(ValidationCheck("output location", True, str(out_path)))

    return ValidationReport(
        ok=all(c.passed for c in checks),
        checks=checks,
        first_error=first_error,
    )
