"""Parallel LaTeX compilation engine.

Compiles animation frames in parallel using ``ProcessPoolExecutor``.
Each frame is compiled in an isolated cache directory to prevent
auxiliary-file conflicts between concurrent workers.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from concurrent.futures import (
    Future,
    ProcessPoolExecutor,
    as_completed,
)
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from tikzgif.bbox import extract_bbox_from_pdf
from tikzgif.cache import CompilationCache
from tikzgif.exceptions import BoundingBoxError, CompilationError
from tikzgif.template import (
    generate_frame_specs,
    parse_template,
)
from tikzgif.types import (
    BoundingBox,
    CompilationConfig,
    ErrorPolicy,
    FrameResult,
    FrameSpec,
    LatexEngine,
)

from .engine import (
    build_compile_command,
    format_errors,
    parse_log,
    select_engine,
)

logger = logging.getLogger(__name__)


def _compile_single_frame(
    spec: FrameSpec,
    cache_root: Path,
    engine: LatexEngine,
    shell_escape: bool,
    extra_args: list[str],
    timeout_s: float,
) -> FrameResult:
    """Compile a single frame's ``.tex`` source to PDF.

    This function runs inside a worker process. It writes the ``.tex``
    source to a content-hash-keyed directory, invokes the LaTeX engine,
    and extracts the bounding box from the resulting PDF.

    Args:
        spec: Frame specification containing source and metadata.
        cache_root: Root directory of the compilation cache.
        engine: LaTeX engine to use.
        shell_escape: Whether to enable ``--shell-escape``.
        extra_args: Additional arguments forwarded to the engine.
        timeout_s: Maximum seconds before the compilation is killed.

    Returns:
        A ``FrameResult`` indicating success or failure.
    """
    t0 = time.monotonic()

    h = spec.content_hash
    frame_dir = cache_root / "frames" / h[:2] / h[2:]
    frame_dir.mkdir(parents=True, exist_ok=True)

    tex_path = frame_dir / "frame.tex"
    pdf_path = frame_dir / "frame.pdf"
    log_path = frame_dir / "frame.log"

    tex_path.write_text(spec.tex_content, encoding="utf-8")

    cmd = build_compile_command(
        engine=engine,
        tex_path=tex_path,
        output_dir=frame_dir,
        shell_escape=shell_escape,
        extra_args=extra_args,
    )

    effective_timeout = timeout_s if timeout_s > 0 else None

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            cwd=str(frame_dir),
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        if pdf_path.is_file():
            pdf_path.unlink()
        return FrameResult(
            index=spec.index,
            success=False,
            error_message=(
                f"Frame {spec.index} timed out after {timeout_s:.0f}s. "
                f"Increase timeout_per_frame_s if your TikZ code is complex."
            ),
            compile_time_s=elapsed,
        )

    elapsed = time.monotonic() - t0

    if not pdf_path.is_file():
        errors = parse_log(log_path)
        return FrameResult(
            index=spec.index,
            success=False,
            error_message=format_errors(errors),
            compile_time_s=elapsed,
        )

    bbox: BoundingBox | None = None
    try:
        bbox = extract_bbox_from_pdf(pdf_path)
    except BoundingBoxError:
        logger.debug("Bounding-box extraction failed for frame %d", spec.index)

    return FrameResult(
        index=spec.index,
        success=True,
        pdf_path=pdf_path,
        bounding_box=bbox,
        compile_time_s=elapsed,
    )


class ProgressReporter:
    """Simple inline progress reporter writing to stderr."""

    def __init__(self, total: int, description: str = "Compiling") -> None:
        self.total = total
        self.completed = 0
        self.description = description

    def update(self, n: int = 1, suffix: str = "") -> None:
        """Record *n* completed items and refresh the display."""
        self.completed += n
        pct = (self.completed / self.total) * 100 if self.total else 100
        line = f"\r{self.description}: {self.completed}/{self.total} ({pct:.0f}%)"
        if suffix:
            line += f" {suffix}"
        print(line, end="", flush=True, file=sys.stderr)

    def close(self) -> None:
        """Finalize the progress display with a newline."""
        if self.completed > 0:
            print(file=sys.stderr)


def _determine_worker_count(config: CompilationConfig) -> int:
    """Return the number of parallel workers to use.

    Defaults to ``cpu_count() - 1`` (minimum 1) unless overridden by
    ``config.max_workers``.
    """
    if config.max_workers > 0:
        return config.max_workers
    cpu = os.cpu_count() or 2
    return max(1, cpu - 1)


def compile_frames(
    specs: list[FrameSpec],
    config: CompilationConfig,
    cache: CompilationCache,
    packages: set[str] | None = None,
    on_frame_done: Callable[[FrameResult], None] | None = None,
) -> list[FrameResult]:
    """Compile a list of frame specifications in parallel.

    Args:
        specs: Frame specifications (one per animation frame).
        config: Compilation settings (engine, workers, timeouts, etc.).
        cache: Content-addressable compilation cache.
        packages: Detected LaTeX packages for engine auto-selection.
        on_frame_done: Optional callback invoked after each frame completes.

    Returns:
        ``FrameResult`` list ordered by frame index.

    Raises:
        CompilationError: If ``error_policy`` is ``ABORT`` and any frame fails.
    """
    workers = _determine_worker_count(config)
    engine = select_engine(preferred=config.engine, packages=packages)
    results: dict[int, FrameResult] = {}
    to_compile: list[FrameSpec] = []
    progress = ProgressReporter(len(specs), "Compiling frames")
    cached_count = 0

    for spec in specs:
        cached_pdf = None if config.no_cache else cache.get_pdf_path(spec.content_hash)
        if cached_pdf is not None:
            bbox = cache.get_bbox(spec.content_hash)
            if bbox is None:
                try:
                    bbox = extract_bbox_from_pdf(cached_pdf)
                    cache.store_bbox(spec.content_hash, bbox)
                except Exception:
                    logger.debug(
                        "Bbox extraction failed for cached frame %d", spec.index,
                    )
            results[spec.index] = FrameResult(
                index=spec.index,
                success=True,
                pdf_path=cached_pdf,
                bounding_box=bbox,
                cached=True,
                compile_time_s=0.0,
            )
            cached_count += 1
            progress.update(suffix=f"cached={cached_count}")
        else:
            to_compile.append(spec)

    if not to_compile:
        progress.close()
        logger.info("All %d frames served from cache.", len(specs))
        return [results[spec.index] for spec in specs]

    logger.info(
        "%d/%d frames cached, compiling %d.",
        cached_count, len(specs), len(to_compile),
    )

    retry_queue: list[FrameSpec] = []

    with ProcessPoolExecutor(max_workers=workers) as pool:
        future_to_spec: dict[Future[FrameResult], FrameSpec] = {}
        for spec in to_compile:
            fut = pool.submit(
                _compile_single_frame,
                spec=spec,
                cache_root=cache.root,
                engine=engine,
                shell_escape=config.shell_escape,
                extra_args=config.extra_args,
                timeout_s=config.timeout_per_frame_s,
            )
            future_to_spec[fut] = spec

        for fut in as_completed(future_to_spec):
            spec = future_to_spec[fut]
            try:
                result = fut.result()
            except Exception as exc:
                result = FrameResult(
                    index=spec.index,
                    success=False,
                    error_message=f"Worker exception: {exc}",
                )

            if result.success:
                if result.bounding_box is not None:
                    cache.store_bbox(spec.content_hash, result.bounding_box)
                results[spec.index] = result
                progress.update(suffix=f"frame {spec.index} OK")
            else:
                if config.error_policy == ErrorPolicy.ABORT:
                    progress.close()
                    for pending_fut in future_to_spec:
                        pending_fut.cancel()
                    raise CompilationError(
                        f"Frame {spec.index} failed to compile:\n"
                        f"{result.error_message}",
                        frame_index=spec.index,
                    )
                elif config.error_policy == ErrorPolicy.RETRY:
                    retry_queue.append(spec)
                    progress.update(suffix=f"frame {spec.index} queued for retry")
                else:
                    results[spec.index] = result
                    progress.update(suffix=f"frame {spec.index} SKIP")
                    logger.warning(
                        "Frame %d failed (skipped): %s",
                        spec.index, result.error_message,
                    )

            if on_frame_done is not None:
                on_frame_done(result)

    if retry_queue:
        logger.info("Retrying %d failed frames...", len(retry_queue))
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_spec = {}
            for spec in retry_queue:
                fut = pool.submit(
                    _compile_single_frame,
                    spec=spec,
                    cache_root=cache.root,
                    engine=engine,
                    shell_escape=config.shell_escape,
                    extra_args=config.extra_args,
                    timeout_s=config.timeout_per_frame_s * 2,
                )
                future_to_spec[fut] = spec

            for fut in as_completed(future_to_spec):
                spec = future_to_spec[fut]
                try:
                    result = fut.result()
                except Exception as exc:
                    result = FrameResult(
                        index=spec.index,
                        success=False,
                        error_message=f"Retry worker exception: {exc}",
                    )

                results[spec.index] = result
                if result.success:
                    if result.bounding_box is not None:
                        cache.store_bbox(spec.content_hash, result.bounding_box)
                    progress.update(suffix=f"frame {spec.index} RETRY OK")
                else:
                    progress.update(suffix=f"frame {spec.index} FAILED")
                    logger.warning(
                        "Frame %d failed after retry: %s",
                        spec.index, result.error_message,
                    )

    progress.close()

    ordered: list[FrameResult] = []
    for spec in specs:
        if spec.index in results:
            ordered.append(results[spec.index])
        else:
            ordered.append(FrameResult(
                index=spec.index,
                success=False,
                error_message="Frame was not compiled (internal error).",
            ))
    return ordered


def compile_single_pass(
    source: str,
    param_values: list[float],
    config: CompilationConfig,
    param_token: str = r"\PARAM",
    extra_preamble: str = "",
    enforced_bbox: BoundingBox | None = None,
) -> list[FrameResult]:
    """Compile all frames in a single pass without automatic bbox normalization.

    Parses the template, generates per-frame ``.tex`` sources, and
    dispatches them to ``compile_frames()`` for parallel compilation.

    Args:
        source: Raw LaTeX template source.
        param_values: Parameter sweep values (one per frame).
        config: Compilation settings.
        param_token: Token to substitute in the template body.
        extra_preamble: Additional LaTeX preamble to inject.
        enforced_bbox: Fixed bounding box to inject into each frame.

    Returns:
        ``FrameResult`` list ordered by frame index.
    """
    parsed = parse_template(source, param_token)
    config_for_job = config
    if parsed.needs_shell_escape and not config.shell_escape:
        config_for_job = replace(config, shell_escape=True)

    cache = CompilationCache(root=config_for_job.cache_dir)

    specs = generate_frame_specs(
        parsed, param_values,
        enforced_bbox=enforced_bbox,
        extra_preamble=extra_preamble,
    )
    return compile_frames(
        specs, config_for_job, cache, packages=parsed.detected_packages
    )
