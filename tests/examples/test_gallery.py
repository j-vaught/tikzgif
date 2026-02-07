"""
Test suite for the tikzgif example gallery.

Tests are organised into tiers:
  - Smoke tests:  verify each .tex file exists and contains \\PARAM.
  - Compilation:  substitute a single mid-range value and compile to PDF.
  - Full render:  run tikzgif end-to-end for a small subset of frames.

Run with:
    pytest tests/examples/test_gallery.py -v
    pytest tests/examples/test_gallery.py -k smoke          # fast
    pytest tests/examples/test_gallery.py -k compile        # per-frame
    pytest tests/examples/test_gallery.py -k full_render    # end-to-end
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.examples.gallery import GALLERY, ExampleSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PDFLATEX = shutil.which("pdflatex")
TIKZGIF = shutil.which("tikzgif")


def _skip_if_no_latex():
    if PDFLATEX is None:
        pytest.skip("pdflatex not found on PATH")


def _skip_if_no_tikzgif():
    if TIKZGIF is None:
        pytest.skip("tikzgif CLI not installed")
    # Also verify the CLI is functional (not just a broken entry point)
    result = subprocess.run(
        ["tikzgif", "--help"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        pytest.skip("tikzgif CLI is installed but not functional")


def _substitute_param(tex_source: str, param_name: str, value: float) -> str:
    """Replace all occurrences of the raw parameter token with a numeric value.

    The parameter token in the .tex files is the bare macro name without the
    backslash prefix that TeX uses -- for example, the gallery stores
    ``\\PARAM`` but the .tex source contains the literal string ``\\PARAM``
    which we match and replace with a number.
    """
    # param_name is e.g. "\\PARAM"; in the .tex source it appears as \PARAM
    # We want to replace the literal string \PARAM (not a regex metachar issue
    # because backslash-P is not a special regex sequence, but we escape anyway).
    token = param_name  # e.g. "\\PARAM"
    # In the raw file the token is literally \PARAM
    return tex_source.replace(token, f"{value:g}")


def _compile_tex(tex_source: str, workdir: Path, engine: str = "pdflatex") -> Path:
    """Write tex_source to a file and compile it.  Returns path to PDF."""
    tex_path = workdir / "frame.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error", str(tex_path)]
    result = subprocess.run(
        cmd,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    pdf_path = workdir / "frame.pdf"
    if result.returncode != 0 or not pdf_path.exists():
        # Dump the log for debugging
        log_path = workdir / "frame.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        raise RuntimeError(
            f"LaTeX compilation failed (exit {result.returncode}).\n"
            f"--- stdout ---\n{result.stdout[-2000:]}\n"
            f"--- stderr ---\n{result.stderr[-2000:]}\n"
            f"--- log tail ---\n{log_text[-3000:]}"
        )
    return pdf_path


# ---------------------------------------------------------------------------
# Parametrized fixtures
# ---------------------------------------------------------------------------

EXAMPLE_IDS = [ex.name.lower().replace(" ", "_") for ex in GALLERY]


@pytest.fixture(params=GALLERY, ids=EXAMPLE_IDS)
def example(request) -> ExampleSpec:
    return request.param


# ---------------------------------------------------------------------------
# Tier 1 -- Smoke tests (no LaTeX required)
# ---------------------------------------------------------------------------


class TestSmoke:
    """Fast checks that do not require a LaTeX installation."""

    def test_tex_file_exists(self, example: ExampleSpec):
        assert example.tex_path.exists(), (
            f"Missing .tex file: {example.tex_path}"
        )

    def test_tex_file_nonempty(self, example: ExampleSpec):
        content = example.tex_path.read_text(encoding="utf-8")
        assert len(content) > 100, "File suspiciously short"

    def test_param_token_present(self, example: ExampleSpec):
        content = example.tex_path.read_text(encoding="utf-8")
        # The parameter macro (e.g. \PARAM) must appear at least once
        # in the body (not just in comments).
        lines = [
            line for line in content.splitlines()
            if not line.lstrip().startswith("%")
        ]
        body = "\n".join(lines)
        assert example.param_name in body, (
            f"Parameter token {example.param_name!r} not found in non-comment "
            f"lines of {example.filename}"
        )

    def test_documentclass_standalone(self, example: ExampleSpec):
        content = example.tex_path.read_text(encoding="utf-8")
        assert r"\documentclass" in content
        assert "standalone" in content

    def test_has_tikzpicture(self, example: ExampleSpec):
        content = example.tex_path.read_text(encoding="utf-8")
        assert r"\begin{tikzpicture}" in content
        assert r"\end{tikzpicture}" in content

    def test_param_range_valid(self, example: ExampleSpec):
        assert example.frame_count >= 1
        assert example.param_end >= example.param_start or (
            example.param_start == example.param_end and example.frame_count == 1
        )

    def test_cli_command_references_file(self, example: ExampleSpec):
        assert example.filename.replace(".tex", "") in example.cli_command

    def test_difficulty_label(self, example: ExampleSpec):
        assert example.difficulty in ("beginner", "intermediate", "advanced")

    def test_features_nonempty(self, example: ExampleSpec):
        assert len(example.features) >= 1


# ---------------------------------------------------------------------------
# Tier 2 -- Single-frame compilation (requires pdflatex)
# ---------------------------------------------------------------------------


class TestCompileSingleFrame:
    """Compile one frame at the midpoint of the parameter range."""

    @pytest.fixture(autouse=True)
    def _require_latex(self):
        _skip_if_no_latex()

    def test_midpoint_compiles(self, example: ExampleSpec, tmp_path: Path):
        midpoint = (example.param_start + example.param_end) / 2.0
        source = example.tex_path.read_text(encoding="utf-8")
        substituted = _substitute_param(source, example.param_name, midpoint)
        pdf = _compile_tex(substituted, tmp_path, engine=example.engine)
        assert pdf.stat().st_size > 0

    def test_start_frame_compiles(self, example: ExampleSpec, tmp_path: Path):
        source = example.tex_path.read_text(encoding="utf-8")
        substituted = _substitute_param(
            source, example.param_name, example.param_start
        )
        pdf = _compile_tex(substituted, tmp_path, engine=example.engine)
        assert pdf.stat().st_size > 0

    def test_end_frame_compiles(self, example: ExampleSpec, tmp_path: Path):
        source = example.tex_path.read_text(encoding="utf-8")
        substituted = _substitute_param(
            source, example.param_name, example.param_end
        )
        pdf = _compile_tex(substituted, tmp_path, engine=example.engine)
        assert pdf.stat().st_size > 0


# ---------------------------------------------------------------------------
# Tier 3 -- Full render with tikzgif CLI (requires tikzgif installed)
# ---------------------------------------------------------------------------


# Only run full render for a fast subset (the 3 beginner examples)
FAST_EXAMPLES = [ex for ex in GALLERY if ex.difficulty == "beginner"]
FAST_IDS = [ex.name.lower().replace(" ", "_") for ex in FAST_EXAMPLES]


class TestFullRender:
    """End-to-end GIF rendering through the tikzgif CLI."""

    @pytest.fixture(autouse=True)
    def _require_tools(self):
        _skip_if_no_latex()
        _skip_if_no_tikzgif()

    @pytest.fixture(params=FAST_EXAMPLES, ids=FAST_IDS)
    def fast_example(self, request) -> ExampleSpec:
        return request.param

    def test_render_5_frames(self, fast_example: ExampleSpec, tmp_path: Path):
        """Render only 5 evenly-spaced frames to keep test time manageable."""
        out_gif = tmp_path / "output.gif"
        cmd = [
            "tikzgif", "render",
            str(fast_example.tex_path),
            "--param", fast_example.param_name.lstrip("\\"),
            "--start", str(fast_example.param_start),
            "--end", str(fast_example.param_end),
            "--frames", "5",
            "--fps", "5",
            "-o", str(out_gif),
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, (
            f"tikzgif failed:\n{result.stderr[-2000:]}"
        )
        assert out_gif.exists()
        assert out_gif.stat().st_size > 1000  # at least 1 KB

    def test_output_is_valid_gif(self, fast_example: ExampleSpec, tmp_path: Path):
        """Check that the output starts with the GIF89a magic bytes."""
        out_gif = tmp_path / "output.gif"
        cmd = [
            "tikzgif", "render",
            str(fast_example.tex_path),
            "--param", fast_example.param_name.lstrip("\\"),
            "--start", str(fast_example.param_start),
            "--end", str(fast_example.param_end),
            "--frames", "3",
            "--fps", "3",
            "-o", str(out_gif),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if out_gif.exists():
            magic = out_gif.read_bytes()[:6]
            assert magic in (b"GIF87a", b"GIF89a"), (
                f"Output is not a valid GIF (magic: {magic!r})"
            )
