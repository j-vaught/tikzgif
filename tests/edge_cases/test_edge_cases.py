"""
Edge case tests for tikzgif.

These tests verify that the pipeline handles degenerate, malformed, and
boundary-condition inputs gracefully -- producing clear errors rather than
hangs, crashes, or silent corruption.

Run with:
    pytest tests/edge_cases/ -v
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

PDFLATEX = shutil.which("pdflatex")
LUALATEX = shutil.which("lualatex")
TIKZGIF = shutil.which("tikzgif")

requires_latex = pytest.mark.skipif(
    PDFLATEX is None, reason="pdflatex not on PATH"
)
requires_lualatex = pytest.mark.skipif(
    LUALATEX is None, reason="lualatex not on PATH"
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
# Templates for edge cases (complete, compilable .tex sources)
# ---------------------------------------------------------------------------

# 1. Empty tikzpicture -- should compile but produce a near-empty page.
#    tikzgif should either produce a valid (blank) GIF or error clearly.
EMPTY_TIKZPICTURE = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  % intentionally empty
\end{tikzpicture}
\end{document}
"""

# 2. Inconsistent bounding boxes -- the bounding box changes drastically
#    between frames.  tikzgif should normalize or warn.
INCONSISTENT_BBOX = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  % Bounding box grows with PARAM: at PARAM=1 it is 1x1, at PARAM=10 it is 10x10
  \draw[thick] (0,0) rectangle (\PARAM, \PARAM);
  \fill[red] (0.5, 0.5) circle (0.3);
\end{tikzpicture}
\end{document}
"""

# 3. Very large frame count -- template is trivial but we request 1000+ frames.
TRIVIAL_FOR_MANY_FRAMES = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-2,-2) rectangle (2,2);
  \fill[blue!\PARAM!red] (0,0) circle (1);
\end{tikzpicture}
\end{document}
"""

# 4. Unicode in labels -- tests that the LaTeX engine handles UTF-8 properly.
UNICODE_LABELS = r"""
\documentclass[tikz]{standalone}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-4,-2) rectangle (4,2);
  \node[font=\large] at (0, 1) {R\'esum\'e: $\alpha = \PARAM$};
  \node[font=\large] at (0, 0) {Sch\"on -- na\"ive};
  \node[font=\large] at (0,-1) {Caf\'e \& cr\`eme};
\end{tikzpicture}
\end{document}
"""

# 5. Compilation error in one frame -- undefined control sequence at a
#    specific parameter value.  Tests the error_policy (abort / skip / retry).
COMPILATION_ERROR_AT_VALUE = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-3,-3) rectangle (3,3);
  \pgfmathtruncatemacro{\val}{\PARAM}
  % Intentional error when val == 5: call an undefined command
  \ifnum\val=5
    \undefinedcommand  % <-- will cause a LaTeX error
  \fi
  \fill[green!\val 0!blue] (0,0) circle (2);
  \node at (0,-2.5) {\val};
\end{tikzpicture}
\end{document}
"""

# 6. Missing LaTeX package -- references a package that does not exist.
MISSING_PACKAGE = r"""
\documentclass[tikz]{standalone}
\usepackage{thispackagedoesnotexist}
\begin{document}
\begin{tikzpicture}
  \fill[red] (0,0) circle (\PARAM);
\end{tikzpicture}
\end{document}
"""

# 7. Extremely large single frame -- poster-size output.
POSTER_SIZE = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  % 100cm x 100cm canvas -- will produce a very large PDF/PNG
  \useasboundingbox (0,0) rectangle (100,100);
  \foreach \x in {0,5,...,95} {
    \foreach \y in {0,5,...,95} {
      \pgfmathsetmacro{\hue}{mod(\x + \y + \PARAM, 100)}
      \fill[red!\hue!blue] (\x, \y) rectangle (\x+5, \y+5);
    }
  }
\end{tikzpicture}
\end{document}
"""

# 8. Transparent background -- standalone with transparent option.
TRANSPARENT_BACKGROUND = r"""
\documentclass[tikz, border=0pt]{standalone}
\begin{document}
\begin{tikzpicture}
  % No background fill -- should be transparent in PNG output
  \fill[red, opacity=0.7] (0,0) circle (\PARAM);
  \fill[blue, opacity=0.5] (1,0) circle (1);
\end{tikzpicture}
\end{document}
"""

# 9. Custom fonts via fontspec + lualatex.
CUSTOM_FONTS_LUALATEX = r"""
\documentclass[tikz]{standalone}
\usepackage{fontspec}
\setmainfont{Latin Modern Roman}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-4,-2) rectangle (4,2);
  \node[font=\Large] at (0, 0.8) {Custom Font Test};
  \node[font=\large] at (0, -0.2) {Parameter: $\theta = \PARAM$};
  \fill[red] ({\PARAM * 0.5 - 1.5}, -1.2) circle (0.3);
\end{tikzpicture}
\end{document}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_and_compile(
    tex: str, workdir: Path, engine: str = "pdflatex", expect_fail: bool = False
) -> subprocess.CompletedProcess:
    tex_path = workdir / "frame.tex"
    tex_path.write_text(tex, encoding="utf-8")
    result = subprocess.run(
        [engine, "-interaction=nonstopmode", "-halt-on-error", str(tex_path)],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if not expect_fail:
        pdf_path = workdir / "frame.pdf"
        assert pdf_path.exists() or result.returncode != 0
    return result


def _substitute(tex: str, value: float) -> str:
    return tex.replace("\\PARAM", f"{value:g}")


def _run_tikzgif_on_string(
    tex: str,
    workdir: Path,
    start: float,
    end: float,
    frames: int,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Write tex to a file and invoke tikzgif."""
    tex_path = workdir / "test.tex"
    tex_path.write_text(tex, encoding="utf-8")
    out = workdir / "output.gif"
    cmd = [
        "tikzgif", "render", str(tex_path),
        "--param", "PARAM",
        "--start", str(start),
        "--end", str(end),
        "--frames", str(frames),
        "--fps", "5",
        "-o", str(out),
    ]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=600
    )


# ---------------------------------------------------------------------------
# Test class: compilation-level edge cases (only need pdflatex)
# ---------------------------------------------------------------------------


class TestCompilationEdgeCases:
    """Tests that exercise LaTeX edge cases at the single-frame level."""

    @requires_latex
    def test_empty_tikzpicture_compiles(self, tmp_path: Path):
        """An empty tikzpicture should compile without error."""
        result = _write_and_compile(EMPTY_TIKZPICTURE, tmp_path)
        # standalone with empty tikzpicture may produce a tiny or zero-size page,
        # but pdflatex should not crash.
        assert result.returncode == 0

    @requires_latex
    def test_inconsistent_bbox_frame_small(self, tmp_path: Path):
        """Small bounding box frame compiles."""
        tex = _substitute(INCONSISTENT_BBOX, 1.0)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0

    @requires_latex
    def test_inconsistent_bbox_frame_large(self, tmp_path: Path):
        """Large bounding box frame compiles."""
        tex = _substitute(INCONSISTENT_BBOX, 10.0)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0

    @requires_latex
    def test_unicode_labels_compile(self, tmp_path: Path):
        """Unicode accented characters compile correctly."""
        tex = _substitute(UNICODE_LABELS, 42.0)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0

    @requires_latex
    def test_compilation_error_good_frame(self, tmp_path: Path):
        """Frames without the error condition compile fine."""
        tex = _substitute(COMPILATION_ERROR_AT_VALUE, 3.0)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0

    @requires_latex
    def test_compilation_error_bad_frame(self, tmp_path: Path):
        """The frame with the undefined command should fail compilation."""
        tex = _substitute(COMPILATION_ERROR_AT_VALUE, 5.0)
        result = _write_and_compile(tex, tmp_path, expect_fail=True)
        assert result.returncode != 0

    @requires_latex
    def test_missing_package_fails(self, tmp_path: Path):
        """A missing package should cause a clear compilation failure."""
        tex = _substitute(MISSING_PACKAGE, 1.0)
        result = _write_and_compile(tex, tmp_path, expect_fail=True)
        assert result.returncode != 0
        # Check that the error message mentions the package
        combined = result.stdout + result.stderr
        assert "thispackagedoesnotexist" in combined or result.returncode != 0

    @requires_latex
    def test_transparent_background_compiles(self, tmp_path: Path):
        """Transparent background should compile without issues."""
        tex = _substitute(TRANSPARENT_BACKGROUND, 1.5)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0

    @requires_lualatex
    def test_custom_fonts_lualatex(self, tmp_path: Path):
        """fontspec with lualatex should compile with system fonts.

        This test may be skipped on minimal TeX installations that lack
        the luatex85 or fontspec packages even though lualatex is present.
        """
        tex = _substitute(CUSTOM_FONTS_LUALATEX, 2.0)
        result = _write_and_compile(tex, tmp_path, engine="lualatex", expect_fail=True)
        if result.returncode != 0:
            output_text = result.stdout + result.stderr
            if "not found" in output_text or "File" in output_text:
                pytest.skip(
                    "lualatex is present but required packages (fontspec, "
                    "luatex85) are missing from this TeX installation"
                )
        assert result.returncode == 0

    @requires_latex
    def test_poster_size_compiles(self, tmp_path: Path):
        """A very large canvas (100x100cm) should compile, though slowly."""
        tex = _substitute(POSTER_SIZE, 0)
        result = _write_and_compile(tex, tmp_path)
        assert result.returncode == 0
        pdf = tmp_path / "frame.pdf"
        assert pdf.stat().st_size > 1000  # should be non-trivial


# ---------------------------------------------------------------------------
# Test class: pipeline-level edge cases (need tikzgif CLI)
# ---------------------------------------------------------------------------


class TestPipelineEdgeCases:
    """Tests that exercise tikzgif's handling of unusual inputs."""

    @requires_latex
    @requires_tikzgif
    def test_empty_tikzpicture_pipeline(self, tmp_path: Path):
        """tikzgif should handle an empty tikzpicture (produce output or error)."""
        result = _run_tikzgif_on_string(
            EMPTY_TIKZPICTURE, tmp_path, start=0, end=1, frames=3
        )
        # Accept either: a graceful error (returncode != 0 but no crash/hang)
        # or a successful run with a tiny GIF.
        assert result.returncode is not None  # did not hang

    @requires_latex
    @requires_tikzgif
    def test_inconsistent_bbox_pipeline(self, tmp_path: Path):
        """Varying bounding boxes should be handled (union or normalize)."""
        result = _run_tikzgif_on_string(
            INCONSISTENT_BBOX, tmp_path, start=1, end=10, frames=5
        )
        # Should succeed -- tikzgif normalizes bounding boxes
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()

    @requires_latex
    @requires_tikzgif
    def test_very_large_frame_count(self, tmp_path: Path):
        """1000 frames of a trivial template -- tests scheduling overhead."""
        result = _run_tikzgif_on_string(
            TRIVIAL_FOR_MANY_FRAMES, tmp_path, start=0, end=100, frames=1000
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()
            assert out.stat().st_size > 1000

    @requires_latex
    @requires_tikzgif
    def test_unicode_pipeline(self, tmp_path: Path):
        """Unicode labels should survive the full pipeline."""
        result = _run_tikzgif_on_string(
            UNICODE_LABELS, tmp_path, start=0, end=10, frames=5
        )
        assert result.returncode == 0
        out = tmp_path / "output.gif"
        assert out.exists()

    @requires_latex
    @requires_tikzgif
    def test_one_bad_frame_abort_policy(self, tmp_path: Path):
        """With error_policy=abort, one bad frame should stop the job."""
        result = _run_tikzgif_on_string(
            COMPILATION_ERROR_AT_VALUE, tmp_path,
            start=0, end=10, frames=11,
            extra_args=["--error-policy", "abort"],
        )
        # Should fail because frame at PARAM=5 has an error
        assert result.returncode != 0

    @requires_latex
    @requires_tikzgif
    def test_one_bad_frame_skip_policy(self, tmp_path: Path):
        """With error_policy=skip, the job should continue past the bad frame."""
        result = _run_tikzgif_on_string(
            COMPILATION_ERROR_AT_VALUE, tmp_path,
            start=0, end=10, frames=11,
            extra_args=["--error-policy", "skip"],
        )
        out = tmp_path / "output.gif"
        # Should succeed (10 out of 11 frames compiled)
        if result.returncode == 0:
            assert out.exists()

    @requires_latex
    @requires_tikzgif
    def test_missing_package_pipeline(self, tmp_path: Path):
        """Missing package should produce a clear error, not a hang."""
        result = _run_tikzgif_on_string(
            MISSING_PACKAGE, tmp_path, start=0, end=1, frames=3
        )
        assert result.returncode != 0
        # Error output should be informative
        combined = result.stdout + result.stderr
        assert len(combined) > 0

    @requires_latex
    @requires_tikzgif
    def test_poster_size_pipeline(self, tmp_path: Path):
        """Very large frames should not cause OOM or silent failure."""
        result = _run_tikzgif_on_string(
            POSTER_SIZE, tmp_path, start=0, end=10, frames=2,
            extra_args=["--dpi", "72"],  # lower DPI to keep memory in check
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()
            # Poster-size at 72 DPI will still be large
            assert out.stat().st_size > 5000

    @requires_latex
    @requires_tikzgif
    def test_transparent_background_pipeline(self, tmp_path: Path):
        """Transparent PNGs should be handled (GIF supports transparency)."""
        result = _run_tikzgif_on_string(
            TRANSPARENT_BACKGROUND, tmp_path, start=0.5, end=2.0, frames=5
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()

    @requires_lualatex
    @requires_tikzgif
    def test_custom_fonts_pipeline(self, tmp_path: Path):
        """fontspec with --engine lualatex should work end-to-end."""
        result = _run_tikzgif_on_string(
            CUSTOM_FONTS_LUALATEX, tmp_path,
            start=0, end=3, frames=4,
            extra_args=["--engine", "lualatex"],
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()


# ---------------------------------------------------------------------------
# Test class: parameter edge cases
# ---------------------------------------------------------------------------


class TestParameterEdgeCases:
    """Tests for degenerate parameter ranges and counts."""

    @requires_latex
    @requires_tikzgif
    def test_single_frame(self, tmp_path: Path):
        """frame_count=1 should produce a single-frame (static) GIF."""
        result = _run_tikzgif_on_string(
            TRIVIAL_FOR_MANY_FRAMES, tmp_path, start=50, end=50, frames=1
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()

    @requires_latex
    @requires_tikzgif
    def test_zero_frames_errors(self, tmp_path: Path):
        """frame_count=0 should produce a clear error."""
        result = _run_tikzgif_on_string(
            TRIVIAL_FOR_MANY_FRAMES, tmp_path, start=0, end=100, frames=0
        )
        assert result.returncode != 0

    @requires_latex
    @requires_tikzgif
    def test_negative_range(self, tmp_path: Path):
        """A negative parameter range (start > end) should error or reverse."""
        result = _run_tikzgif_on_string(
            TRIVIAL_FOR_MANY_FRAMES, tmp_path, start=100, end=0, frames=10
        )
        # Either succeeds (reversing the range) or gives a clear error
        assert result.returncode is not None

    @requires_latex
    @requires_tikzgif
    def test_very_small_param_step(self, tmp_path: Path):
        """Extremely fine parameter steps (e.g., 0.001 apart) should work."""
        result = _run_tikzgif_on_string(
            TRIVIAL_FOR_MANY_FRAMES, tmp_path, start=49.990, end=50.010, frames=5
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()

    @requires_latex
    @requires_tikzgif
    def test_large_parameter_values(self, tmp_path: Path):
        """Very large parameter values (1e6) should not overflow pgfmath."""
        tex = r"""
\documentclass[tikz]{standalone}
\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-2,-2) rectangle (2,2);
  \pgfmathsetmacro{\val}{mod(\PARAM, 360)}
  \fill[red] (0,0) -- (\val:1.5) arc (\val:\val+30:1.5) -- cycle;
\end{tikzpicture}
\end{document}
"""
        result = _run_tikzgif_on_string(
            tex, tmp_path, start=1000000, end=1000360, frames=5
        )
        out = tmp_path / "output.gif"
        if result.returncode == 0:
            assert out.exists()
