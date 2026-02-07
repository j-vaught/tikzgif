"""
Parallel LaTeX compilation engine.

Architecture
------------
This module uses ``concurrent.futures.ProcessPoolExecutor`` for parallel
compilation.  Each frame is compiled in an independent subprocess via
``subprocess.run()``.

Design rationale:

  - **ProcessPoolExecutor over multiprocessing.Pool**: Cleaner API,
    built-in Future semantics, better exception propagation, and
    natural integration with ``as_completed()`` for progress reporting.

  - **subprocess.run inside each worker** (not asyncio): LaTeX compilation
    is CPU-bound and I/O-heavy (disk writes).  asyncio subprocess support
    adds complexity without benefit because we are not multiplexing
    thousands of connections -- we have at most ``cpu_count()`` concurrent
    compilations.

  - **Isolated working directories**: Each frame is compiled in its own
    directory (provided by the content-addressable cache).  This is
    mandatory because pdflatex writes .aux, .log, and .pdf files with
    names derived from the input.  If two processes compile in the same
    directory, they clobber each other's auxiliary files.

Worker count
------------
Default: ``os.cpu_count() - 1`` (leave one core for the orchestrator and
OS).  Minimum 1.  User can override via ``CompilationConfig.max_workers``.

Progress reporting
------------------
Uses ``concurrent.futures.as_completed()`` to report results as they
finish, driving a tqdm progress bar (or a simple fallback printer).

Error handling
--------------
- ABORT:  On first failure, cancel pending futures and raise.
- SKIP:   Log the error, mark the frame as failed, continue.
- RETRY:  On failure, resubmit once with doubled timeout.  If retry fails, skip.
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
from pathlib import Path
from typing import Callable

from tikzgif.bbox import (
    compute_envelope,
    extract_bbox_from_pdf,
    select_probe_indices,
)
from tikzgif.cache import CompilationCache
from tikzgif.engine import (
    build_compile_command,
    format_errors,
    parse_log,
    select_engine,
)
from tikzgif.exceptions import BoundingBoxError, CompilationError
from tikzgif.tex_gen import (
    ParsedTemplate,
    generate_frame_specs,
    parse_template,
    template_structure_hash,
)
from tikzgif.types import (
    BoundingBox,
    CompilationConfig,
    ErrorPolicy,
    FrameResult,
    FrameSpec,
    LatexEngine,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-frame compilation (runs in worker process)
# ---------------------------------------------------------------------------

def _compile_single_frame(
    spec: FrameSpec,
    cache_root: Path,
    engine: LatexEngine,
    shell_escape: bool,
    extra_args: list[str],
    timeout_s: float,
) -> FrameResult:
    """
    Compile a single frame's .tex file to PDF.

    This function runs in a worker process.  It:
      1. Writes the .tex source to an isolated cache directory.
      2. Runs the LaTeX engine.
      3. Extracts the bounding box from the resulting PDF.
      4. Returns a FrameResult.
    """
    t0 = time.monotonic()

    # Each frame gets its own directory keyed by content hash.
    # This prevents .aux file conflicts between parallel workers.
    h = spec.content_hash
    frame_dir = cache_root / "frames" / h[:2] / h[2:]
    frame_dir.mkdir(parents=True, exist_ok=True)

    tex_path = frame_dir / "frame.tex"
    pdf_path = frame_dir / "frame.pdf"
    log_path = frame_dir / "frame.log"

    # Write .tex source.
    tex_path.write_text(spec.tex_content, encoding="utf-8")

    # Build and run the compilation command.
    cmd = build_compile_command(
        engine=engine,
        tex_path=tex_path,
        output_dir=frame_dir,
        shell_escape=shell_escape,
        extra_args=extra_args,
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(frame_dir),
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - t0
        return FrameResult(
            index=spec.index,
            success=False,
            error_message=(
                f"Frame {spec.index} timed out after {timeout_s:.0f}s.  "
                f"Increase timeout_per_frame_s if your TikZ code is complex."
            ),
            compile_time_s=elapsed,
        )

    elapsed = time.monotonic() - t0

    # Check for success.
    if not pdf_path.is_file():
        errors = parse_log(log_path)
        return FrameResult(
            index=spec.index,
            success=False,
            error_message=format_errors(errors),
            compile_time_s=elapsed,
        )

    # Extract bounding box from the PDF.
    bbox: BoundingBox | None = None
    try:
        bbox = extract_bbox_from_pdf(pdf_path)
    except BoundingBoxError:
        pass  # Non-fatal: bbox extraction is best-effort.

    return FrameResult(
        index=spec.index,
        success=True,
        pdf_path=pdf_path,
        bounding_box=bbox,
        compile_time_s=elapsed,
    )


# ---------------------------------------------------------------------------
# Progress reporting
# ---------------------------------------------------------------------------

class ProgressReporter:
    """
    Thin abstraction over progress reporting.

    Uses tqdm if available; otherwise prints to stderr.
    """

    def __init__(self, total: int, description: str = "Compiling") -> None:
        self.total = total
        self.completed = 0
        self.description = description
        self._bar: Any = None
        try:
            from tqdm import tqdm
            self._bar = tqdm(
                total=total, desc=description, unit="frame",
                file=sys.stderr, dynamic_ncols=True,
            )
        except ImportError:
            pass

    def update(self, n: int = 1, suffix: str = "") -> None:
        self.completed += n
        if self._bar is not None:
            if suffix:
                self._bar.set_postfix_str(suffix)
            self._bar.update(n)
        else:
            pct = (self.completed / self.total) * 100 if self.total else 100
            print(
                f"\r{self.description}: {self.completed}/{self.total} "
                f"({pct:.0f}%) {suffix}",
                end="", flush=True, file=sys.stderr,
            )

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
        else:
            if self.completed > 0:
                print(file=sys.stderr)  # newline


# Need Any for tqdm type
from typing import Any  # noqa: E402


# ---------------------------------------------------------------------------
# Orchestrator: parallel compilation
# ---------------------------------------------------------------------------

def _determine_worker_count(config: CompilationConfig) -> int:
    """Determine how many parallel workers to use."""
    if config.max_workers > 0:
        return config.max_workers
    cpu = os.cpu_count() or 2
    return max(1, cpu - 1)


def compile_frames(
    specs: list[FrameSpec],
    config: CompilationConfig,
    cache: CompilationCache,
    on_frame_done: Callable[[FrameResult], None] | None = None,
) -> list[FrameResult]:
    """
    Compile a list of frame specifications in parallel.

    This is the core entry point for the compilation engine.

    Parameters
    ----------
    specs : list[FrameSpec]
        Frame specifications (one per animation frame).
    config : CompilationConfig
        Compilation settings.
    cache : CompilationCache
        The compilation cache.
    on_frame_done : callable, optional
        Callback invoked after each frame completes.

    Returns
    -------
    list[FrameResult]
        Results in frame-index order.

    Raises
    ------
    CompilationError
        If error_policy is ABORT and any frame fails.
    """
    workers = _determine_worker_count(config)
    engine = select_engine(preferred=config.engine, packages=None)
    results: dict[int, FrameResult] = {}
    to_compile: list[FrameSpec] = []
    progress = ProgressReporter(len(specs), "Compiling frames")
    cached_count = 0

    # -- Phase 1: Check cache ----------------------------------------------
    for spec in specs:
        cached_pdf = cache.get_pdf_path(spec.content_hash)
        if cached_pdf is not None:
            bbox = cache.get_bbox(spec.content_hash)
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

    # -- Phase 2: Parallel compilation -------------------------------------
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
                        f"{result.error_message}"
                    )
                elif config.error_policy == ErrorPolicy.RETRY:
                    retry_queue.append(spec)
                    progress.update(suffix=f"frame {spec.index} queued for retry")
                else:  # SKIP
                    results[spec.index] = result
                    progress.update(suffix=f"frame {spec.index} SKIP")
                    logger.warning(
                        "Frame %d failed (skipped): %s",
                        spec.index, result.error_message,
                    )

            if on_frame_done is not None:
                on_frame_done(result)

    # -- Phase 3: Retry failed frames --------------------------------------
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

    # -- Assemble ordered results ------------------------------------------
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


# ---------------------------------------------------------------------------
# Two-pass compilation with bounding-box normalization
# ---------------------------------------------------------------------------

def compile_with_bbox_normalization(
    source: str,
    param_values: list[float],
    config: CompilationConfig,
    param_token: str = r"\PARAM",
    extra_preamble: str = "",
) -> tuple[list[FrameResult], BoundingBox]:
    """
    Full two-pass compilation pipeline with automatic bounding-box
    normalization.

    Pass 1 ("probe"):
        Compile a sampled subset of frames without a forced bounding box.
        Extract each frame's natural bounding box.  Compute the envelope.

    Pass 2 ("final"):
        Re-generate all frames with the envelope injected as
        \\useasboundingbox.  Compile in parallel.

    If the template already contains \\useasboundingbox, the probe pass
    is skipped.

    Parameters
    ----------
    source : str
        Complete parameterized .tex file content.
    param_values : list[float]
        Parameter values, one per frame.
    config : CompilationConfig
        Compilation configuration.
    param_token : str
        The placeholder token.
    extra_preamble : str
        Additional preamble content.

    Returns
    -------
    (results, envelope)
        results: list of FrameResult in frame order.
        envelope: the bounding box enforced on all frames.
    """
    parsed = parse_template(source, param_token)
    cache = CompilationCache(root=config.cache_dir)

    # -- Short circuit: user already specified bounding box ----------------
    if parsed.has_bounding_box:
        logger.info(
            "Template contains \\useasboundingbox; skipping probe pass."
        )
        specs = generate_frame_specs(
            parsed, param_values,
            enforced_bbox=None,
            extra_preamble=extra_preamble,
        )
        results = compile_frames(specs, config, cache)

        # Extract bbox from first successful frame for reporting.
        envelope = BoundingBox(0, 0, 100, 100)  # fallback
        for r in results:
            if r.success and r.bounding_box is not None:
                envelope = r.bounding_box
                break

        return results, envelope

    # -- Pass 1: Probe for bounding boxes ----------------------------------
    logger.info("Pass 1: Probing bounding boxes (%d samples)...",
                config.max_probes)

    probe_indices = select_probe_indices(
        len(param_values), max_probes=config.max_probes
    )

    # Generate specs for ALL frames (no enforced bbox), then select probes.
    all_specs_no_bbox = generate_frame_specs(
        parsed, param_values,
        enforced_bbox=None,
        extra_preamble=extra_preamble,
    )
    probe_specs = [all_specs_no_bbox[i] for i in probe_indices]

    probe_results = compile_frames(probe_specs, config, cache)

    # Collect bounding boxes.
    probe_bboxes: list[BoundingBox] = []
    for result in probe_results:
        if result.success and result.bounding_box is not None:
            probe_bboxes.append(result.bounding_box)

    if not probe_bboxes:
        raise BoundingBoxError(
            "All probe frames failed to compile.  Cannot determine bounding "
            "box.  Fix the LaTeX errors and try again."
        )

    raw_envelope = compute_envelope(probe_bboxes)
    # Apply padding so content does not touch the edge.
    envelope = raw_envelope.padded(config.bbox_padding_bp)

    logger.info(
        "Bounding-box envelope: (%.1f, %.1f) -- (%.1f, %.1f)  "
        "[%.1f x %.1f bp]",
        envelope.x_min, envelope.y_min,
        envelope.x_max, envelope.y_max,
        envelope.width, envelope.height,
    )

    # -- Pass 2: Final compilation with enforced bbox ----------------------
    logger.info("Pass 2: Compiling all %d frames with enforced bounding box...",
                len(param_values))

    final_specs = generate_frame_specs(
        parsed, param_values,
        enforced_bbox=envelope,
        extra_preamble=extra_preamble,
    )

    # Store template metadata for future cache lookups.
    tmpl_hash = template_structure_hash(parsed)
    frame_map = {s.index: s.content_hash for s in final_specs}
    cache.store_template_meta(tmpl_hash, frame_map)

    final_results = compile_frames(final_specs, config, cache)
    return final_results, envelope


# ---------------------------------------------------------------------------
# Single-pass compilation
# ---------------------------------------------------------------------------

def compile_single_pass(
    source: str,
    param_values: list[float],
    config: CompilationConfig,
    param_token: str = r"\PARAM",
    extra_preamble: str = "",
    enforced_bbox: BoundingBox | None = None,
) -> list[FrameResult]:
    """
    Single-pass compilation without automatic bbox normalization.

    Use this when the user has provided \\useasboundingbox in their
    template, or when they have explicitly disabled normalization.
    """
    parsed = parse_template(source, param_token)
    cache = CompilationCache(root=config.cache_dir)

    specs = generate_frame_specs(
        parsed, param_values,
        enforced_bbox=enforced_bbox,
        extra_preamble=extra_preamble,
    )
    return compile_frames(specs, config, cache)
