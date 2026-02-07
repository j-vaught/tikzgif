"""
Tests for the template schema, registry, and CLI subsystem.
"""

import textwrap
from pathlib import Path

import pytest

from tikzgif.template_schema import (
    Template,
    TemplateMeta,
    TemplateParam,
    ParamType,
    parse_template,
)
from tikzgif.template_registry import TemplateRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_TEMPLATE = textwrap.dedent(r"""
%%--- TIKZGIF META ---
%% name: test.minimal
%% title: Minimal Test
%% description: A test template.
%% author: Test
%% version: 1.0.0
%% domain: test
%% tags: [test]
%% engine: pdflatex
%% tikz_libraries: [arrows.meta]
%% latex_packages: [tikz]
%% params:
%%   - name: t
%%     type: float
%%     default: 0.5
%%     min: 0.0
%%     max: 1.0
%%     step: 0.1
%%     sweep: true
%%     description: Test parameter
%%     unit: ""
%% fps: 10
%% frames: 11
%% loop: true
%% bounce: false
%%--- END META ---
\documentclass[border=5pt,tikz]{standalone}
\usepackage{tikz}
\begin{document}
\begin{tikzpicture}
\draw (0,0) -- ({{{ t }}}, 0);
\end{tikzpicture}
\end{document}
""").strip()


MULTI_PARAM_TEMPLATE = textwrap.dedent(r"""
%%--- TIKZGIF META ---
%% name: test.multi
%% title: Multi-Parameter
%% description: Template with sweep and static params.
%% author: Test
%% version: 1.0.0
%% domain: test
%% tags: [test]
%% engine: pdflatex
%% tikz_libraries: []
%% latex_packages: [tikz]
%% params:
%%   - name: K
%%     type: float
%%     default: 2.0
%%     min: 0.1
%%     max: 10.0
%%     step: 0.5
%%     sweep: true
%%     description: Gain
%%   - name: color
%%     type: choice
%%     default: blue
%%     choices: [red, green, blue]
%%     sweep: false
%%     description: Line color
%% fps: 10
%% frames: 20
%%--- END META ---
\documentclass{standalone}
\usepackage{tikz}
\begin{document}
\begin{tikzpicture}
\draw[{{{ color }}}, thick] (0,0) circle ({{{ K }}});
\end{tikzpicture}
\end{document}
""").strip()


# ---------------------------------------------------------------------------
# Tests: parse_template
# ---------------------------------------------------------------------------

class TestParseTemplate:
    def test_parse_minimal(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        assert tpl.meta.name == "test.minimal"
        assert tpl.meta.title == "Minimal Test"
        assert tpl.meta.domain == "test"
        assert tpl.meta.engine == "pdflatex"
        assert len(tpl.meta.params) == 1
        assert tpl.meta.params[0].name == "t"
        assert tpl.meta.params[0].is_sweep is True
        assert tpl.meta.params[0].minimum == 0.0
        assert tpl.meta.params[0].maximum == 1.0
        assert tpl.meta.recommended_frames == 11

    def test_parse_multi_param(self):
        tpl = parse_template(MULTI_PARAM_TEMPLATE)
        assert len(tpl.meta.params) == 2
        assert tpl.meta.sweep_params[0].name == "K"
        assert tpl.meta.static_params[0].name == "color"

    def test_missing_delimiters_raises(self):
        with pytest.raises(ValueError, match="missing"):
            parse_template(r"\documentclass{standalone}\begin{document}\end{document}")

    def test_tikz_libraries_parsed(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        assert "arrows.meta" in tpl.meta.tikz_libraries

    def test_tex_body_extracted(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        assert r"\documentclass" in tpl.tex_body
        assert r"{{{ t }}}" in tpl.tex_body
        assert "TIKZGIF META" not in tpl.tex_body


# ---------------------------------------------------------------------------
# Tests: TemplateParam.sweep_values
# ---------------------------------------------------------------------------

class TestSweepValues:
    def test_step_based(self):
        p = TemplateParam(name="t", minimum=0.0, maximum=1.0, step=0.5, is_sweep=True)
        vals = p.sweep_values()
        assert vals == [0.0, 0.5, 1.0]

    def test_frame_count_override(self):
        p = TemplateParam(name="t", minimum=0.0, maximum=1.0, step=0.1, is_sweep=True)
        vals = p.sweep_values(n_frames=3)
        assert len(vals) == 3
        assert abs(vals[0] - 0.0) < 1e-10
        assert abs(vals[-1] - 1.0) < 1e-10

    def test_single_frame(self):
        p = TemplateParam(name="t", minimum=0.0, maximum=1.0, is_sweep=True)
        vals = p.sweep_values(n_frames=1)
        assert len(vals) == 1
        assert vals[0] == 0.0

    def test_no_range_raises(self):
        p = TemplateParam(name="t", is_sweep=True)
        with pytest.raises(ValueError, match="no min/max"):
            p.sweep_values()


# ---------------------------------------------------------------------------
# Tests: Template.render_frame
# ---------------------------------------------------------------------------

class TestRenderFrame:
    def test_simple_substitution(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        result = tpl.render_frame({"t": 0.75})
        assert "{{{ t }}}" not in result
        assert "0.75" in result

    def test_multi_param_substitution(self):
        tpl = parse_template(MULTI_PARAM_TEMPLATE)
        result = tpl.render_frame({"K": 5.0, "color": "red"})
        assert "5" in result
        assert "red" in result
        assert "{{{ K }}}" not in result
        assert "{{{ color }}}" not in result

    def test_default_used_when_missing(self):
        tpl = parse_template(MULTI_PARAM_TEMPLATE)
        result = tpl.render_frame({"K": 3.0})
        assert "blue" in result


# ---------------------------------------------------------------------------
# Tests: Template.generate_all_frames
# ---------------------------------------------------------------------------

class TestGenerateAllFrames:
    def test_frame_count(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        frames = list(tpl.generate_all_frames(n_frames=5))
        assert len(frames) == 5

    def test_frame_indices_sequential(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        frames = list(tpl.generate_all_frames(n_frames=5))
        indices = [f[0] for f in frames]
        assert indices == [0, 1, 2, 3, 4]

    def test_sweep_values_in_frames(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        frames = list(tpl.generate_all_frames(n_frames=3))
        assert abs(frames[0][1]["t"] - 0.0) < 1e-10
        assert abs(frames[-1][1]["t"] - 1.0) < 1e-10

    def test_tex_content_differs_per_frame(self):
        tpl = parse_template(MINIMAL_TEMPLATE)
        frames = list(tpl.generate_all_frames(n_frames=3))
        sources = {f[2] for f in frames}
        assert len(sources) == 3

    def test_static_template_single_frame(self):
        src = MINIMAL_TEMPLATE.replace("sweep: true", "sweep: false")
        tpl = parse_template(src)
        frames = list(tpl.generate_all_frames())
        assert len(frames) == 1


# ---------------------------------------------------------------------------
# Tests: TemplateRegistry
# ---------------------------------------------------------------------------

class TestTemplateRegistry:
    def test_scan_builtin_templates(self):
        reg = TemplateRegistry()
        reg.scan()
        metas = reg.list_templates()
        names = [m.name for m in metas]
        assert len(names) >= 10
        assert "control.step_response" in names
        assert "em.wave_propagation" in names
        assert "physics.fourier_series" in names

    def test_get_existing(self):
        reg = TemplateRegistry()
        tpl = reg.get("control.step_response")
        assert tpl.meta.domain == "control_systems"
        assert any(p.is_sweep for p in tpl.meta.params)

    def test_get_nonexistent_raises(self):
        reg = TemplateRegistry()
        with pytest.raises(KeyError, match="not found"):
            reg.get("nonexistent.template")

    def test_domains(self):
        reg = TemplateRegistry()
        domains = reg.domains()
        assert "control_systems" in domains
        assert "electromagnetics" in domains
        assert "general_physics" in domains

    def test_filter_by_domain(self):
        reg = TemplateRegistry()
        ctrl = reg.list_templates(domain="control_systems")
        for m in ctrl:
            assert m.domain == "control_systems"
        assert len(ctrl) >= 4

    def test_register_custom(self):
        reg = TemplateRegistry()
        tpl = parse_template(MINIMAL_TEMPLATE)
        reg.register(tpl)
        fetched = reg.get("test.minimal")
        assert fetched.meta.title == "Minimal Test"

    def test_extra_dirs(self, tmp_path):
        custom = MINIMAL_TEMPLATE.replace("test.minimal", "control.step_response")
        custom = custom.replace("Minimal Test", "Custom Override")
        tex_file = tmp_path / "control_step_override.tex"
        tex_file.write_text(custom)
        reg = TemplateRegistry(extra_dirs=[tmp_path])
        tpl = reg.get("control.step_response")
        assert tpl.meta.title == "Custom Override"


# ---------------------------------------------------------------------------
# Tests: All built-in templates parse correctly
# ---------------------------------------------------------------------------

class TestBuiltinTemplateParsing:
    @pytest.fixture
    def builtin_tex_files(self):
        builtin = Path(__file__).resolve().parent.parent / "tikzgif" / "templates"
        return sorted(f for f in builtin.rglob("*.tex") if not f.name.startswith("."))

    def test_all_templates_parse(self, builtin_tex_files):
        for tex_file in builtin_tex_files:
            raw = tex_file.read_text(encoding="utf-8")
            try:
                tpl = parse_template(raw, source_path=tex_file)
            except Exception as exc:
                pytest.fail(f"Failed to parse {tex_file.name}: {exc}")
            assert tpl.meta.name, f"{tex_file.name} has empty name"

    def test_all_domain_templates_have_sweep(self, builtin_tex_files):
        for tex_file in builtin_tex_files:
            raw = tex_file.read_text(encoding="utf-8")
            tpl = parse_template(raw, source_path=tex_file)
            if tpl.meta.domain not in ("base", ""):
                sweeps = [p for p in tpl.meta.params if p.is_sweep]
                assert len(sweeps) >= 1, f"{tpl.meta.name} has no sweep parameter"

    def test_all_templates_generate_frames(self, builtin_tex_files):
        for tex_file in builtin_tex_files:
            raw = tex_file.read_text(encoding="utf-8")
            tpl = parse_template(raw, source_path=tex_file)
            if tpl.meta.domain in ("base", ""):
                continue
            frames = list(tpl.generate_all_frames(n_frames=3))
            assert len(frames) == 3, f"{tpl.meta.name} did not produce 3 frames"
            for idx, vals, tex in frames:
                assert "{{{ " not in tex, (
                    f"{tpl.meta.name} frame {idx} has unsubstituted placeholder"
                )
