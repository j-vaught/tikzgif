"""Template parsing and frame generation for token-based TikZ templates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tikzgif.exceptions import TemplateError
from tikzgif.types import BoundingBox, FrameSpec

DEFAULT_PARAM_TOKEN = r"\\PARAM"

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

SHELL_ESCAPE_PACKAGES = frozenset(
    {
        "minted",
        "pythontex",
        "svg",
        "gnuplot-lua-tikz",
    }
)


@dataclass
class ParsedTemplate:
    """Result of parsing a parameterized ``.tex`` template.

    Attributes:
        original_source: Unmodified template source text.
        preamble_lines: Lines before ``\\begin{document}``.
        body_lines: Lines between ``\\begin{document}`` and ``\\end{document}``.
        postamble_lines: Lines from ``\\end{document}`` onward.
        document_class: LaTeX document class name.
        class_options: Options passed to ``\\documentclass``.
        detected_packages: Set of ``\\usepackage`` names found.
        needs_shell_escape: Whether detected packages require ``--shell-escape``.
        has_bounding_box: Whether the body contains ``\\useasboundingbox``.
        param_token: The parameter token used for substitution.
    """

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


def parse_template(source: str, param_token: str = DEFAULT_PARAM_TOKEN) -> ParsedTemplate:
    """Parse template source and validate required LaTeX structure.

    Args:
        source: Raw LaTeX template text.
        param_token: Parameter token to look for in the document body.

    Returns:
        A ``ParsedTemplate`` with extracted metadata.

    Raises:
        TemplateError: If required LaTeX structure is missing or the
            parameter token is not found in the document body.
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
    class_options = [opt.strip() for opt in raw_opts.split(",") if opt.strip()]

    packages: set[str] = set()
    for m_pkg in _RE_USEPACKAGE.finditer(preamble_str):
        for pkg_name in m_pkg.group("packages").split(","):
            pkg = pkg_name.strip()
            if pkg:
                packages.add(pkg)

    shell_escape = bool(packages & SHELL_ESCAPE_PACKAGES)
    has_bbox = bool(_RE_BOUNDING_BOX.search(body_str))

    if param_token not in body_str:
        raise TemplateError(
            f"Parameter token '{param_token}' not found between "
            f"\\begin{{document}} and \\end{{document}}. "
            f"Place {param_token} in your TikZ code where the animated value should be substituted."
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


def parse_template_from_file(path: Path, param_token: str = DEFAULT_PARAM_TOKEN) -> ParsedTemplate:
    """Read and parse a template from disk.

    Args:
        path: Path to the ``.tex`` template file.
        param_token: Parameter token to look for.

    Returns:
        A ``ParsedTemplate`` with extracted metadata.

    Raises:
        TemplateError: If the file cannot be read or parsing fails.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"Cannot read template file: {exc}") from exc
    return parse_template(source, param_token)


def _build_standalone_preamble(parsed: ParsedTemplate, extra_preamble: str = "") -> str:
    """Build a ``standalone`` preamble preserving package imports from the source.

    Args:
        parsed: Previously parsed template.
        extra_preamble: Additional preamble text to append.

    Returns:
        Complete preamble string for a standalone document.
    """
    lines: list[str] = []
    user_opts = [opt for opt in parsed.class_options if opt not in ("tikz",)]
    opts = ["tikz"] + user_opts
    if not any(opt.startswith("border") for opt in opts):
        opts.append("border=2pt")
    lines.append(f"\\documentclass[{', '.join(opts)}]{{standalone}}\n")

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
    """Substitute the parameter value and optionally inject a fixed bounding box.

    Args:
        parsed: Previously parsed template.
        param_value: Value to substitute for the parameter token.
        enforced_bbox: Bounding box to inject, or ``None``.

    Returns:
        Processed body string with substitutions applied.
    """
    body = "".join(parsed.body_lines)
    body = body.replace(parsed.param_token, f"{param_value:g}")

    if enforced_bbox is not None and not parsed.has_bounding_box:
        bbox_reset = "  \\pgfresetboundingbox\n" + "  " + enforced_bbox.to_tikz_clip() + "\n"
        end_tikz = re.compile(r"(\\end\s*\{tikzpicture\})")
        match = end_tikz.search(body)
        if match:
            body = body[: match.start()] + bbox_reset + body[match.start() :]

    return body


def generate_frame_specs(
    parsed: ParsedTemplate,
    param_values: Sequence[float],
    enforced_bbox: BoundingBox | None = None,
    extra_preamble: str = "",
) -> list[FrameSpec]:
    """Generate complete per-frame LaTeX sources and their content hashes.

    Args:
        parsed: Previously parsed template.
        param_values: Parameter values (one per frame).
        enforced_bbox: Fixed bounding box to inject, or ``None``.
        extra_preamble: Additional preamble text to inject.

    Returns:
        List of ``FrameSpec`` objects ready for compilation.
    """
    preamble = _build_standalone_preamble(parsed, extra_preamble)
    specs: list[FrameSpec] = []

    for index, value in enumerate(param_values):
        body = _build_frame_body(parsed, value, enforced_bbox)
        full_source = preamble + "\\begin{document}\n" + body + "\\end{document}\n"
        content_hash = hashlib.sha256(full_source.encode("utf-8")).hexdigest()
        specs.append(
            FrameSpec(
                index=index,
                param_value=value,
                param_name=parsed.param_token,
                tex_content=full_source,
                content_hash=content_hash,
            )
        )

    return specs
