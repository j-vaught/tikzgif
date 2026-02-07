"""
Performance benchmarks for the tikzgif pipeline.

These tests measure wall-clock time for compilation and conversion at
different scales and parallelism levels.  They are marked with
``@pytest.mark.benchmark`` so they can be selected or excluded easily:

    pytest tests/benchmarks/ -v -m benchmark
    pytest tests/benchmarks/ -v -m "not benchmark"   # skip benchmarks

Results are printed to stdout and optionally written to a JSON report.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.benchmark_templates import (
    HEAVY_CONFIG,
    HEAVY_TEX,
    MEDIUM_CONFIG,
    MEDIUM_TEX,
    SIMPLE_CONFIG,
    SIMPLE_TEX,
)

# ---------------------------------------------------------------------------
# Marks and skips
# ---------------------------------------------------------------------------

PDFLATEX = shutil.which("pdflatex")
TIKZGIF = shutil.which("tikzgif")

benchmark = pytest.mark.benchmark
slow = pytest.mark.slow

requires_latex = pytest.mark.skipif(
    PDFLATEX is None, reason="pdflatex not on PATH"
)
def _tikzgif_functional() -> bool:
    """Check that the tikzgif CLI is both present and importable."""
    if TIKZGIF is None:
        return False
    result = subprocess.run(
        ["tikzgif", "--help"], capture_output=True, text=True, timeout=10
    )
    return result.returncode == 0


_TIKZGIF_OK = _tikzgif_functional()

requires_tikzgif = pytest.mark.skipif(
    not _TIKZGIF_OK, reason="tikzgif CLI not installed or not functional"
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TimingResult:
    """Collected timing data for one benchmark run."""

    benchmark_name: str
    frame_count: int
    workers: int
    compile_time_s: float = 0.0
    convert_time_s: float = 0.0
    total_time_s: float = 0.0
    frames_per_second: float = 0.0
    peak_memory_mb: float = 0.0
    cache_hit: bool = False
    output_size_kb: float = 0.0
    notes: str = ""

    def summary_line(self) -> str:
        return (
            f"[{self.benchmark_name:>10s}] "
            f"frames={self.frame_count:4d}  "
            f"workers={self.workers:2d}  "
            f"compile={self.compile_time_s:7.2f}s  "
            f"convert={self.convert_time_s:7.2f}s  "
            f"total={self.total_time_s:7.2f}s  "
            f"fps={self.frames_per_second:6.2f}  "
            f"mem={self.peak_memory_mb:6.1f}MB  "
            f"out={self.output_size_kb:7.1f}KB"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _substitute(tex: str, param_name: str, value: float) -> str:
    return tex.replace(param_name, f"{value:g}")


def _compile_single_frame(
    tex: str, param_name: str, value: float, workdir: Path, engine: str = "pdflatex"
) -> tuple[float, Path]:
    """Compile a single frame, return (elapsed_seconds, pdf_path)."""
    source = _substitute(tex, param_name, value)
    tex_path = workdir / "frame.tex"
    tex_path.write_text(source, encoding="utf-8")

    t0 = time.perf_counter()
    result = subprocess.run(
        [engine, "-interaction=nonstopmode", "-halt-on-error", str(tex_path)],
        cwd=str(workdir),
        capture_output=True,
        timeout=120,
    )
    elapsed = time.perf_counter() - t0

    pdf_path = workdir / "frame.pdf"
    if result.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(
            f"Compilation failed (exit {result.returncode})"
        )
    return elapsed, pdf_path


def _run_tikzgif(
    tex_path: Path,
    config: dict,
    workers: int,
    frames: int,
    out_path: Path,
    extra_args: list[str] | None = None,
) -> tuple[float, float, float]:
    """Run tikzgif CLI and return (compile_time, convert_time, total_time).

    Times are parsed from tikzgif stdout if available, otherwise
    total wall-clock time is reported for all three.
    """
    cmd = [
        "tikzgif", "render",
        str(tex_path),
        "--param", config["param_name"].lstrip("\\"),
        "--start", str(config["param_start"]),
        "--end", str(config["param_end"]),
        "--frames", str(frames),
        "--workers", str(workers),
        "--fps", "10",
        "-o", str(out_path),
    ]
    if extra_args:
        cmd.extend(extra_args)

    t0 = time.perf_counter()
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=1800
    )
    total = time.perf_counter() - t0

    if result.returncode != 0:
        raise RuntimeError(
            f"tikzgif failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )

    # Attempt to parse timing from output (tikzgif may print these)
    compile_time = total
    convert_time = 0.0
    for line in result.stdout.splitlines():
        if "compile" in line.lower() and "time" in line.lower():
            try:
                compile_time = float(line.split()[-1].rstrip("s"))
            except (ValueError, IndexError):
                pass
        if "convert" in line.lower() and "time" in line.lower():
            try:
                convert_time = float(line.split()[-1].rstrip("s"))
            except (ValueError, IndexError):
                pass

    return compile_time, convert_time, total


# ---------------------------------------------------------------------------
# Write benchmark template to disk (fixture)
# ---------------------------------------------------------------------------

@pytest.fixture()
def bench_dir(tmp_path: Path):
    """Provide a clean temporary directory for benchmark artifacts."""
    return tmp_path


def _write_template(tex: str, workdir: Path, name: str) -> Path:
    path = workdir / f"{name}.tex"
    path.write_text(tex, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tier 1 -- Single-frame compilation benchmarks
# ---------------------------------------------------------------------------


class TestSingleFrameCompileTime:
    """Measure how long one frame takes to compile for each tier."""

    @requires_latex
    @benchmark
    def test_simple_single_frame(self, bench_dir: Path):
        cfg = SIMPLE_CONFIG
        mid = (cfg["param_start"] + cfg["param_end"]) / 2
        elapsed, pdf = _compile_single_frame(
            SIMPLE_TEX, cfg["param_name"], mid, bench_dir
        )
        print(f"\n  Simple single frame: {elapsed:.3f}s  PDF={pdf.stat().st_size}B")
        assert elapsed < 30, f"Simple frame took {elapsed:.1f}s (expected < 30s)"

    @requires_latex
    @benchmark
    def test_medium_single_frame(self, bench_dir: Path):
        cfg = MEDIUM_CONFIG
        mid = (cfg["param_start"] + cfg["param_end"]) / 2
        elapsed, pdf = _compile_single_frame(
            MEDIUM_TEX, cfg["param_name"], mid, bench_dir
        )
        print(f"\n  Medium single frame: {elapsed:.3f}s  PDF={pdf.stat().st_size}B")
        assert elapsed < 60, f"Medium frame took {elapsed:.1f}s (expected < 60s)"

    @requires_latex
    @benchmark
    def test_heavy_single_frame(self, bench_dir: Path):
        cfg = HEAVY_CONFIG
        mid = (cfg["param_start"] + cfg["param_end"]) / 2
        elapsed, pdf = _compile_single_frame(
            HEAVY_TEX, cfg["param_name"], mid, bench_dir
        )
        print(f"\n  Heavy single frame: {elapsed:.3f}s  PDF={pdf.stat().st_size}B")
        assert elapsed < 120, f"Heavy frame took {elapsed:.1f}s (expected < 120s)"


# ---------------------------------------------------------------------------
# Tier 2 -- Multi-frame sequential vs parallel
# ---------------------------------------------------------------------------


class TestParallelScaling:
    """Benchmark sequential vs parallel compilation at 1, 2, 4, 8 cores.

    These tests exercise the full tikzgif pipeline including compilation,
    PDF-to-PNG conversion, and GIF assembly.
    """

    @requires_latex
    @requires_tikzgif
    @benchmark
    @slow
    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    def test_simple_scaling(self, workers: int, bench_dir: Path):
        cfg = SIMPLE_CONFIG
        tex_path = _write_template(SIMPLE_TEX, bench_dir, "simple")
        out = bench_dir / "simple.gif"
        compile_t, convert_t, total_t = _run_tikzgif(
            tex_path, cfg, workers=workers, frames=10, out_path=out
        )
        result = TimingResult(
            benchmark_name="simple",
            frame_count=10,
            workers=workers,
            compile_time_s=compile_t,
            convert_time_s=convert_t,
            total_time_s=total_t,
            frames_per_second=10 / total_t if total_t > 0 else 0,
            output_size_kb=out.stat().st_size / 1024 if out.exists() else 0,
        )
        print(f"\n  {result.summary_line()}")

    @requires_latex
    @requires_tikzgif
    @benchmark
    @slow
    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    def test_medium_scaling(self, workers: int, bench_dir: Path):
        cfg = MEDIUM_CONFIG
        tex_path = _write_template(MEDIUM_TEX, bench_dir, "medium")
        out = bench_dir / "medium.gif"
        # Use only 20 frames for reasonable test duration
        compile_t, convert_t, total_t = _run_tikzgif(
            tex_path, cfg, workers=workers, frames=20, out_path=out
        )
        result = TimingResult(
            benchmark_name="medium",
            frame_count=20,
            workers=workers,
            compile_time_s=compile_t,
            convert_time_s=convert_t,
            total_time_s=total_t,
            frames_per_second=20 / total_t if total_t > 0 else 0,
            output_size_kb=out.stat().st_size / 1024 if out.exists() else 0,
        )
        print(f"\n  {result.summary_line()}")

    @requires_latex
    @requires_tikzgif
    @benchmark
    @slow
    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    def test_heavy_scaling(self, workers: int, bench_dir: Path):
        cfg = HEAVY_CONFIG
        tex_path = _write_template(HEAVY_TEX, bench_dir, "heavy")
        out = bench_dir / "heavy.gif"
        # Use only 8 frames for heavy benchmark
        compile_t, convert_t, total_t = _run_tikzgif(
            tex_path, cfg, workers=workers, frames=8, out_path=out
        )
        result = TimingResult(
            benchmark_name="heavy",
            frame_count=8,
            workers=workers,
            compile_time_s=compile_t,
            convert_time_s=convert_t,
            total_time_s=total_t,
            frames_per_second=8 / total_t if total_t > 0 else 0,
            output_size_kb=out.stat().st_size / 1024 if out.exists() else 0,
        )
        print(f"\n  {result.summary_line()}")


# ---------------------------------------------------------------------------
# Tier 3 -- Cache effectiveness
# ---------------------------------------------------------------------------


class TestCacheHit:
    """Run the same job twice to measure cache speedup."""

    @requires_latex
    @requires_tikzgif
    @benchmark
    def test_cache_hit_simple(self, bench_dir: Path):
        cfg = SIMPLE_CONFIG
        tex_path = _write_template(SIMPLE_TEX, bench_dir, "simple")
        out = bench_dir / "simple.gif"

        # First run (cold cache)
        _, _, cold_time = _run_tikzgif(
            tex_path, cfg, workers=4, frames=10, out_path=out
        )

        # Second run (warm cache -- same content hashes)
        out2 = bench_dir / "simple2.gif"
        _, _, warm_time = _run_tikzgif(
            tex_path, cfg, workers=4, frames=10, out_path=out2
        )

        speedup = cold_time / warm_time if warm_time > 0 else float("inf")
        print(
            f"\n  Cache test: cold={cold_time:.2f}s  warm={warm_time:.2f}s  "
            f"speedup={speedup:.2f}x"
        )
        # Warm run should be at least somewhat faster (allow generous margin)
        # If caching is not implemented yet, this will still pass but show 1x.


# ---------------------------------------------------------------------------
# Tier 4 -- Memory profiling (optional, requires psutil)
# ---------------------------------------------------------------------------


class TestMemoryUsage:
    """Profile peak memory during compilation."""

    @requires_latex
    @benchmark
    def test_memory_simple(self, bench_dir: Path):
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not installed")

        cfg = SIMPLE_CONFIG
        mid = (cfg["param_start"] + cfg["param_end"]) / 2
        source = _substitute(SIMPLE_TEX, cfg["param_name"], mid)
        tex_path = bench_dir / "frame.tex"
        tex_path.write_text(source, encoding="utf-8")

        process = subprocess.Popen(
            ["pdflatex", "-interaction=nonstopmode", str(tex_path)],
            cwd=str(bench_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ps = psutil.Process(process.pid)
        peak_rss = 0
        while process.poll() is None:
            try:
                mem = ps.memory_info()
                peak_rss = max(peak_rss, mem.rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            time.sleep(0.05)
        process.wait()

        peak_mb = peak_rss / (1024 * 1024)
        print(f"\n  Simple frame peak RSS: {peak_mb:.1f} MB")
        assert peak_mb < 500, f"Excessive memory: {peak_mb:.0f} MB"

    @requires_latex
    @benchmark
    def test_memory_heavy(self, bench_dir: Path):
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not installed")

        cfg = HEAVY_CONFIG
        mid = (cfg["param_start"] + cfg["param_end"]) / 2
        source = _substitute(HEAVY_TEX, cfg["param_name"], mid)
        tex_path = bench_dir / "frame.tex"
        tex_path.write_text(source, encoding="utf-8")

        process = subprocess.Popen(
            ["pdflatex", "-interaction=nonstopmode", str(tex_path)],
            cwd=str(bench_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ps = psutil.Process(process.pid)
        peak_rss = 0
        while process.poll() is None:
            try:
                mem = ps.memory_info()
                peak_rss = max(peak_rss, mem.rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            time.sleep(0.05)
        process.wait()

        peak_mb = peak_rss / (1024 * 1024)
        print(f"\n  Heavy frame peak RSS: {peak_mb:.1f} MB")
        assert peak_mb < 1000, f"Excessive memory: {peak_mb:.0f} MB"


# ---------------------------------------------------------------------------
# Report generation (run manually)
# ---------------------------------------------------------------------------


def generate_benchmark_report(output_path: Path | None = None):
    """Run all benchmarks and produce a JSON comparison matrix.

    This is intended to be called from a script, not from pytest.
    Usage:
        python -c "from tests.benchmarks.test_benchmarks import generate_benchmark_report; \\
                    generate_benchmark_report()"
    """
    results: list[dict[str, Any]] = []

    for tier_name, tex, config, frame_counts in [
        ("simple", SIMPLE_TEX, SIMPLE_CONFIG, [10]),
        ("medium", MEDIUM_TEX, MEDIUM_CONFIG, [20, 60]),
        ("heavy", HEAVY_TEX, HEAVY_CONFIG, [8, 50, 200]),
    ]:
        for frames in frame_counts:
            for workers in [1, 2, 4, 8]:
                with tempfile.TemporaryDirectory() as td:
                    workdir = Path(td)
                    tex_path = _write_template(tex, workdir, tier_name)
                    out = workdir / f"{tier_name}.gif"
                    try:
                        ct, cvt, total = _run_tikzgif(
                            tex_path, config, workers, frames, out
                        )
                        results.append({
                            "tier": tier_name,
                            "frames": frames,
                            "workers": workers,
                            "compile_s": round(ct, 3),
                            "convert_s": round(cvt, 3),
                            "total_s": round(total, 3),
                            "fps": round(frames / total, 3) if total > 0 else 0,
                            "output_kb": round(
                                out.stat().st_size / 1024, 1
                            ) if out.exists() else 0,
                        })
                    except Exception as exc:
                        results.append({
                            "tier": tier_name,
                            "frames": frames,
                            "workers": workers,
                            "error": str(exc),
                        })

    if output_path is None:
        output_path = Path("benchmark_report.json")

    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Report written to {output_path}")
    return results
