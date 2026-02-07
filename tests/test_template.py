"""
Tests for the template parsing and frame generation module.
"""

import pytest

from tikzgif.tex_gen import (
    ParsedTemplate,
    generate_frame_specs,
    parse_template,
    template_structure_hash,
)
from tikzgif.types import BoundingBox


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_TEMPLATE = r"""
\documentclass[tikz]{standalone}
\usepackage{tikz}
\usepackage{pgfplots}

\begin{document}
\begin{tikzpicture}
  \draw[thick] (0,0) circle (\PARAM);
\end{tikzpicture}
\end{document}
""".strip()


TEMPLATE_WITH_BBOX = r"""
\documentclass{article}
\usepackage{tikz}

\begin{document}
\begin{tikzpicture}
  \useasboundingbox (-5,-5) rectangle (5,5);
  \draw (0,0) -- (\PARAM, 0);
\end{tikzpicture}
\end{document}
""".strip()


TEMPLATE_NO_PARAM = r"""
\documentclass{standalone}
\usepackage{tikz}

\begin{document}
\begin{tikzpicture}
  \draw (0,0) -- (1,1);
\end{tikzpicture}
\end{document}
""".strip()


TEMPLATE_SHELL_ESCAPE = r"""
\documentclass{standalone}
\usepackage{tikz}
\usepackage{minted}

\begin{document}
\begin{tikzpicture}
  \node at (0, \PARAM) {Hello};
\end{tikzpicture}
\end{document}
""".strip()


# ---------------------------------------------------------------------------
# Tests: parse_template
# ---------------------------------------------------------------------------

class TestParseTemplate:
    def test_basic_parse(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        assert parsed.document_class == "standalone"
        assert "tikz" in parsed.class_options
        assert "tikz" in parsed.detected_packages
        assert "pgfplots" in parsed.detected_packages
        assert not parsed.has_bounding_box
        assert not parsed.needs_shell_escape
        assert parsed.param_token == r"\PARAM"

    def test_detects_bounding_box(self):
        parsed = parse_template(TEMPLATE_WITH_BBOX)
        assert parsed.has_bounding_box

    def test_missing_param_raises(self):
        with pytest.raises(Exception, match="not found"):
            parse_template(TEMPLATE_NO_PARAM)

    def test_missing_begin_document_raises(self):
        with pytest.raises(Exception, match="missing.*begin"):
            parse_template(r"\documentclass{article}")

    def test_missing_end_document_raises(self):
        with pytest.raises(Exception, match="missing.*end"):
            parse_template(
                r"\documentclass{article}" "\n"
                r"\begin{document}" "\n"
                r"\PARAM"
            )

    def test_custom_param_token(self):
        src = SIMPLE_TEMPLATE.replace(r"\PARAM", r"\myvar")
        parsed = parse_template(src, param_token=r"\myvar")
        assert parsed.param_token == r"\myvar"

    def test_shell_escape_detection(self):
        parsed = parse_template(TEMPLATE_SHELL_ESCAPE)
        assert parsed.needs_shell_escape
        assert "minted" in parsed.detected_packages


# ---------------------------------------------------------------------------
# Tests: generate_frame_specs
# ---------------------------------------------------------------------------

class TestGenerateFrameSpecs:
    def test_correct_count(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs = generate_frame_specs(parsed, [1.0, 2.0, 3.0])
        assert len(specs) == 3

    def test_param_substitution(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs = generate_frame_specs(parsed, [3.14])
        assert r"\PARAM" not in specs[0].tex_content
        assert "3.14" in specs[0].tex_content

    def test_standalone_wrapper(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs = generate_frame_specs(parsed, [1.0])
        assert r"\documentclass[" in specs[0].tex_content
        assert "standalone" in specs[0].tex_content

    def test_unique_hashes(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs = generate_frame_specs(parsed, [1.0, 2.0])
        assert specs[0].content_hash != specs[1].content_hash

    def test_deterministic_hashes(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs_a = generate_frame_specs(parsed, [1.0])
        specs_b = generate_frame_specs(parsed, [1.0])
        assert specs_a[0].content_hash == specs_b[0].content_hash

    def test_enforced_bbox_injection(self):
        parsed = parse_template(SIMPLE_TEMPLATE)
        bbox = BoundingBox(-10, -10, 10, 10)
        specs = generate_frame_specs(parsed, [1.0], enforced_bbox=bbox)
        assert r"\useasboundingbox" in specs[0].tex_content

    def test_no_double_bbox(self):
        """If template already has bbox, enforced_bbox should not add another."""
        parsed = parse_template(TEMPLATE_WITH_BBOX)
        bbox = BoundingBox(-10, -10, 10, 10)
        specs = generate_frame_specs(parsed, [1.0], enforced_bbox=bbox)
        count = specs[0].tex_content.count(r"\useasboundingbox")
        assert count == 1  # Only the user's original one.

    def test_integer_param_no_trailing_dot(self):
        """Parameter value 5.0 should appear as '5', not '5.0' or '5.'."""
        parsed = parse_template(SIMPLE_TEMPLATE)
        specs = generate_frame_specs(parsed, [5.0])
        assert "5" in specs[0].tex_content
        # The :g format spec strips trailing zeros.
        assert "5.0" not in specs[0].tex_content


# ---------------------------------------------------------------------------
# Tests: template_structure_hash
# ---------------------------------------------------------------------------

class TestTemplateStructureHash:
    def test_same_template_same_hash(self):
        p1 = parse_template(SIMPLE_TEMPLATE)
        p2 = parse_template(SIMPLE_TEMPLATE)
        assert template_structure_hash(p1) == template_structure_hash(p2)

    def test_different_template_different_hash(self):
        p1 = parse_template(SIMPLE_TEMPLATE)
        modified = SIMPLE_TEMPLATE.replace("circle", "ellipse")
        p2 = parse_template(modified)
        assert template_structure_hash(p1) != template_structure_hash(p2)
