"""
Template parsing and frame generation.

Supports two template syntaxes:

1. **Raw token replacement** (default): The user puts a literal token like
   ``\\PARAM`` in their .tex file.  The engine performs direct string
   substitution.  This is simple, fast, and avoids any delimiter conflicts
   with LaTeX's brace-heavy syntax.

2. **Jinja2 mode**: For advanced use (conditionals, loops), the user can
   opt into Jinja2 with custom delimiters ``<< >>``, ``<% %>``, ``<# #>``
   that do not collide with LaTeX braces.

This module is also responsible for:
  - Parsing the .tex structure (preamble / body / postamble).
  - Detecting packages and shell-escape requirements.
  - Generating standalone-wrapped per-frame .tex sources.
  - Computing content hashes for the caching layer.
  - Computing a "template structure hash" that distinguishes template-level
    changes from parameter-level changes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tikzgif.exceptions import TemplateError
from tikzgif.types import BoundingBox, FrameSpec


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PARAM_TOKEN = r"\PARAM"

_RE_DOCUMENTCLASS = re.compile(
    r"\\documentclass"
    r"(?:\s*\[(?P<options>[^\]]*)\])?"
    r"\s*\{(?P<class>[^}]+)\}",
    re.DOTALL,
)
_RE_BEGIN_DOC = re.compile(r"\\begin\s*\{document\}")
_RE_END_DOC = re.compile(r"\\end\s*\{document\}")

_RE_USEPACKAGE = re.compile(
    r"\\usepackage"
    r"(?:\s*\[(?P<options>[^\]]*)\])?"
    r"\s*\{(?P<packages>[^}]+)\}",
)
_RE_BOUNDING_BOX = re.compile(r"\\useasboundingbox\b")

SHELL_ESCAPE_PACKAGES = frozenset({
    "minted", "pythontex", "svg", "gnuplot-lua-tikz",
})


# ---------------------------------------------------------------------------
# ParsedTemplate
# ---------------------------------------------------------------------------

@dataclass
class ParsedTemplate:
    """Result of parsing a parameterized .tex file."""
    original_source: str
    preamble_lines: list[str]
    body_lines: list[str]
    postamble_lines: list[str]
    document_class: str
    class_options: list[str]
    detected_packages: set[str]
    needs_shell_escape: bool
    has_bounding_box: bool
    param_token: str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_template(
    source: str,
    param_token: str = DEFAULT_PARAM_TOKEN,
) -> ParsedTemplate:
    """
    Parse a parameterized .tex file into its structural components.

    Parameters
    ----------
    source : str
        Complete .tex file content.
    param_token : str
        The placeholder string that represents the animated parameter.

    Returns
    -------
    ParsedTemplate

    Raises
    ------
    TemplateError
        If the source is malformed or the param_token is not found.
    """
    m_begin = _RE_BEGIN_DOC.search(source)
    m_end = _RE_END_DOC.search(source)
    if m_begin is None:
        raise TemplateError("Template is missing \\begin{document}.")
    if m_end is None:
        raise TemplateError("Template is missing \\end{document}.")

    preamble_str = source[: m_begin.start()]
    body_str = source[m_begin.end() : m_end.start()]
    postamble_str = source[m_end.start() :]

    m_class = _RE_DOCUMENTCLASS.search(preamble_str)
    if m_class is None:
        raise TemplateError("Template is missing \\documentclass.")

    doc_class = m_class.group("class").strip()
    raw_opts = m_class.group("options") or ""
    class_options = [o.strip() for o in raw_opts.split(",") if o.strip()]

    packages: set[str] = set()
    for m_pkg in _RE_USEPACKAGE.finditer(preamble_str):
        for pkg_name in m_pkg.group("packages").split(","):
            packages.add(pkg_name.strip())

    shell_escape = bool(packages & SHELL_ESCAPE_PACKAGES)
    has_bbox = bool(_RE_BOUNDING_BOX.search(body_str))

    if param_token not in body_str:
        raise TemplateError(
            f"Parameter token '{param_token}' not found between "
            f"\\begin{{document}} and \\end{{document}}.  "
            f"Place {param_token} in your TikZ code where the animated "
            f"value should be substituted."
        )

    return ParsedTemplate(
        original_source=source,
        preamble_lines=preamble_str.splitlines(keepends=True),
        body_lines=body_str.splitlines(keepends=True),
        postamble_lines=postamble_str.splitlines(keepends=True),
        document_class=doc_class,
        class_options=class_options,
        detected_packages=packages,
        needs_shell_escape=shell_escape,
        has_bounding_box=has_bbox,
        param_token=param_token,
    )


def parse_template_from_file(
    path: Path,
    param_token: str = DEFAULT_PARAM_TOKEN,
) -> ParsedTemplate:
    """Convenience wrapper that reads a file then parses it."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Cannot read template file: {exc}") from exc
    return parse_template(source, param_token)


# ---------------------------------------------------------------------------
# Standalone wrapper generation
# ---------------------------------------------------------------------------

def _build_standalone_preamble(
    parsed: ParsedTemplate,
    extra_preamble: str = "",
) -> str:
    """
    Rebuild the preamble, replacing the original document class with
    ``standalone`` and preserving all \\usepackage declarations.

    The standalone class with the ``tikz`` option produces a tightly
    cropped page around the TikZ picture.
    """
    lines: list[str] = []

    # Preserve user options, ensure "tikz" and a border are present.
    user_opts = [o for o in parsed.class_options if o not in ("tikz",)]
    opts = ["tikz"] + user_opts
    if not any(o.startswith("border") for o in opts):
        opts.append("border=2pt")
    opts_str = ", ".join(opts)
    lines.append(f"\\documentclass[{opts_str}]{{standalone}}\n")

    # Copy everything from the original preamble EXCEPT \\documentclass.
    skipped_docclass = False
    for line in parsed.preamble_lines:
        if not skipped_docclass and _RE_DOCUMENTCLASS.search(line):
            skipped_docclass = True
            continue
        lines.append(line)

    if extra_preamble:
        lines.append(extra_preamble.rstrip("\n") + "\n")

    return "".join(lines)


def _build_frame_body(
    parsed: ParsedTemplate,
    param_value: float,
    enforced_bbox: BoundingBox | None = None,
) -> str:
    """
    Build the body of a single frame's .tex file.

    Substitutes the parameter token with the concrete numeric value and
    optionally injects a \\useasboundingbox directive.
    """
    body = "".join(parsed.body_lines)

    value_str = f"{param_value:g}"
    body = body.replace(parsed.param_token, value_str)

    if enforced_bbox is not None and not parsed.has_bounding_box:
        bbox_cmd = "  " + enforced_bbox.to_tikz_clip() + "\n"
        pattern = re.compile(r"(\\begin\s*\{tikzpicture\}[^\n]*\n)")
        m = pattern.search(body)
        if m:
            insert_pos = m.end()
            body = body[:insert_pos] + bbox_cmd + body[insert_pos:]

    return body


# ---------------------------------------------------------------------------
# Frame spec generation
# ---------------------------------------------------------------------------

def generate_frame_specs(
    parsed: ParsedTemplate,
    param_values: Sequence[float],
    enforced_bbox: BoundingBox | None = None,
    extra_preamble: str = "",
) -> list[FrameSpec]:
    """
    Generate a list of FrameSpec objects, one per animation frame.

    Each FrameSpec contains the complete .tex source for that frame
    (standalone document class, all packages, substituted parameter)
    plus a SHA-256 content hash for the caching layer.
    """
    preamble = _build_standalone_preamble(parsed, extra_preamble)
    specs: list[FrameSpec] = []

    for idx, val in enumerate(param_values):
        body = _build_frame_body(parsed, val, enforced_bbox)
        full_source = (
            preamble
            + "\\begin{document}\n"
            + body
            + "\\end{document}\n"
        )
        content_hash = hashlib.sha256(full_source.encode("utf-8")).hexdigest()
        specs.append(FrameSpec(
            index=idx,
            param_value=val,
            param_name=parsed.param_token,
            tex_content=full_source,
            content_hash=content_hash,
        ))

    return specs


# ---------------------------------------------------------------------------
# Jinja2 mode (optional advanced usage)
# ---------------------------------------------------------------------------

def render_frames_jinja(
    template_path: Path,
    param_name: str,
    param_values: Sequence[float],
) -> list[FrameSpec]:
    """
    Render a Jinja2-parameterized .tex template into per-frame FrameSpecs.

    Uses custom delimiters to avoid conflicts with LaTeX braces:
      - Variables: << variable >>
      - Blocks:    <% block %>
      - Comments:  <# comment #>

    Parameters
    ----------
    template_path : Path
        Path to the .tex file with Jinja2 placeholders.
    param_name : str
        Name of the Jinja2 variable (e.g., "t").
    param_values : Sequence[float]
        One value per frame.

    Returns
    -------
    list[FrameSpec]
    """
    from jinja2 import BaseLoader, Environment
    from jinja2 import TemplateError as JinjaError

    env = Environment(
        loader=BaseLoader(),
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        block_start_string="<%",
        block_end_string="%>",
        autoescape=False,
    )

    try:
        raw = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Cannot read template: {exc}") from exc

    try:
        template = env.from_string(raw)
    except JinjaError as exc:
        raise TemplateError(f"Template syntax error: {exc}") from exc

    frames: list[FrameSpec] = []
    for idx, value in enumerate(param_values):
        try:
            rendered = template.render({param_name: value})
        except JinjaError as exc:
            raise TemplateError(
                f"Render error at frame {idx} ({param_name}={value}): {exc}"
            ) from exc

        content_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        frames.append(FrameSpec(
            index=idx,
            param_value=value,
            param_name=param_name,
            tex_content=rendered,
            content_hash=content_hash,
        ))

    return frames


# ---------------------------------------------------------------------------
# Template structure hash
# ---------------------------------------------------------------------------

def template_structure_hash(parsed: ParsedTemplate) -> str:
    """
    Hash the template structure *without* any parameter values.

    This hash changes when the user modifies the TikZ drawing itself
    but stays constant when only the parameter values change.  Used by
    the caching layer to decide whether to invalidate the entire cache.
    """
    sentinel = "<<PARAM_SENTINEL>>"
    preamble = "".join(parsed.preamble_lines)
    body = "".join(parsed.body_lines).replace(parsed.param_token, sentinel)
    combined = preamble + body
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
