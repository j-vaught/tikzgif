"""
Tests for engine detection, command building, and log parsing.
"""

import textwrap
import pytest
from pathlib import Path

from tikzgif.engine import (
    LatexError,
    build_compile_command,
    detect_available_engines,
    detect_packages,
    detect_tikz_libraries,
    format_errors,
    needs_shell_escape,
    parse_log,
    select_engine,
)
from tikzgif.types import LatexEngine


class TestDetectAvailableEngines:
    def test_returns_dict(self):
        result = detect_available_engines()
        assert isinstance(result, dict)
        for engine in LatexEngine:
            assert engine in result


class TestBuildCompileCommand:
    def test_basic_command(self, tmp_path):
        tex = tmp_path / "test.tex"
        tex.touch()
        cmd = build_compile_command(
            LatexEngine.PDFLATEX, tex, tmp_path,
        )
        assert cmd[0] == "pdflatex"
        assert "-interaction=nonstopmode" in cmd
        assert "-halt-on-error" in cmd
        assert str(tex) in cmd

    def test_shell_escape(self, tmp_path):
        tex = tmp_path / "test.tex"
        tex.touch()
        cmd = build_compile_command(
            LatexEngine.PDFLATEX, tex, tmp_path,
            shell_escape=True,
        )
        assert "--shell-escape" in cmd

    def test_extra_args(self, tmp_path):
        tex = tmp_path / "test.tex"
        tex.touch()
        cmd = build_compile_command(
            LatexEngine.XELATEX, tex, tmp_path,
            extra_args=["-synctex=1"],
        )
        assert cmd[0] == "xelatex"
        assert "-synctex=1" in cmd

    def test_output_directory_set(self, tmp_path):
        tex = tmp_path / "test.tex"
        tex.touch()
        cmd = build_compile_command(
            LatexEngine.PDFLATEX, tex, tmp_path,
        )
        assert any(f"-output-directory={tmp_path}" in arg for arg in cmd)


class TestParseLog:
    def test_missing_log(self, tmp_path):
        errors = parse_log(tmp_path / "nonexistent.log")
        assert len(errors) == 1
        assert "not found" in errors[0].message.lower()

    def test_clean_log(self, tmp_path):
        log = tmp_path / "clean.log"
        log.write_text("This is pdfTeX.\nOutput written on frame.pdf.\n")
        errors = parse_log(log)
        assert len(errors) == 0

    def test_undefined_control_sequence(self, tmp_path):
        log = tmp_path / "error.log"
        log.write_text(textwrap.dedent("""\
            This is pdfTeX, Version 3.14159265
            ! Undefined control sequence.
            l.15 \\badcommand
            \n
        """))
        errors = parse_log(log)
        assert len(errors) >= 1
        assert "Undefined control sequence" in errors[0].message

    def test_missing_package(self, tmp_path):
        log = tmp_path / "error.log"
        log.write_text(textwrap.dedent("""\
            ! LaTeX Error: File `noexist.sty' not found.
            l.3 \\usepackage{noexist}
        """))
        errors = parse_log(log)
        assert len(errors) >= 1
        assert "noexist" in errors[0].message.lower()


class TestFormatErrors:
    def test_empty(self):
        assert "No errors" in format_errors([])

    def test_with_errors(self):
        errs = [
            LatexError(line_number=10, message="Bad thing", context="..."),
            LatexError(line_number=None, message="Worse thing", context="..."),
        ]
        text = format_errors(errs)
        assert "Bad thing" in text
        assert "line 10" in text
        assert "unknown" in text

    def test_verbose_includes_context(self):
        errs = [
            LatexError(line_number=5, message="Error", context="line1\nline2"),
        ]
        text = format_errors(errs, verbose=True)
        assert "line1" in text


class TestDetectPackages:
    def test_single_package(self):
        preamble = r"\usepackage{tikz}"
        assert "tikz" in detect_packages(preamble)

    def test_multiple_packages(self):
        preamble = r"\usepackage{tikz,pgfplots}"
        pkgs = detect_packages(preamble)
        assert "tikz" in pkgs
        assert "pgfplots" in pkgs

    def test_with_options(self):
        preamble = r"\usepackage[utf8]{inputenc}"
        assert "inputenc" in detect_packages(preamble)


class TestDetectTikzLibraries:
    def test_single_library(self):
        preamble = r"\usetikzlibrary{arrows}"
        assert "arrows" in detect_tikz_libraries(preamble)

    def test_multiple_libraries(self):
        preamble = r"\usetikzlibrary{arrows, calc, patterns}"
        libs = detect_tikz_libraries(preamble)
        assert "arrows" in libs
        assert "calc" in libs
        assert "patterns" in libs


class TestNeedsShellEscape:
    def test_minted(self):
        assert needs_shell_escape({"tikz", "minted"})

    def test_no_shell_escape(self):
        assert not needs_shell_escape({"tikz", "pgfplots"})
