"""
Template schema -- data model for parameterized TikZ templates.

Every template is a .tex file with a YAML metadata header delimited by
%%--- TIKZGIF META ---  /  %%--- END META ---.  The header declares
parameters (name, type, range, default, description) and rendering hints
(recommended fps, frame count, required TikZ libraries, engine).

This module defines the Python-side representation of that metadata and
the logic to parse it from raw .tex content.
"""

from __future__ import annotations

import enum
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml


# ---------------------------------------------------------------------------
# Parameter types
# ---------------------------------------------------------------------------

class ParamType(enum.Enum):
    """Supported template parameter types."""
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    CHOICE = "choice"
    COLOR = "color"


@dataclass(frozen=True)
class TemplateParam:
    """Declaration of a single sweep or configuration parameter."""
    name: str
    param_type: ParamType = ParamType.FLOAT
    default: Any = 1.0
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: list[str] | None = None
    description: str = ""
    is_sweep: bool = False
    unit: str = ""

    def sweep_values(self, n_frames: int | None = None) -> list[float]:
        """Generate the list of values this parameter takes across frames."""
        if self.minimum is None or self.maximum is None:
            raise ValueError(f"Parameter '{self.name}' has no min/max for sweep.")
        if n_frames is not None:
            if n_frames < 2:
                return [float(self.minimum)]
            step = (self.maximum - self.minimum) / (n_frames - 1)
            return [self.minimum + i * step for i in range(n_frames)]
        if self.step is not None and self.step > 0:
            vals: list[float] = []
            v = self.minimum
            while v <= self.maximum + 1e-12:
                vals.append(round(v, 10))
                v += self.step
            return vals
        return self.sweep_values(n_frames=30)


# ---------------------------------------------------------------------------
# Template metadata
# ---------------------------------------------------------------------------

@dataclass
class TemplateMeta:
    """Full metadata block parsed from a template file."""
    name: str
    title: str = ""
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    domain: str = ""
    tags: list[str] = field(default_factory=list)
    tikz_libraries: list[str] = field(default_factory=list)
    latex_packages: list[str] = field(default_factory=list)
    engine: str = "pdflatex"
    params: list[TemplateParam] = field(default_factory=list)
    recommended_fps: int = 15
    recommended_frames: int = 30
    loop: bool = True
    bounce: bool = False
    extends: str | None = None

    @property
    def sweep_params(self) -> list[TemplateParam]:
        return [p for p in self.params if p.is_sweep]

    @property
    def static_params(self) -> list[TemplateParam]:
        return [p for p in self.params if not p.is_sweep]

    def get_param(self, name: str) -> TemplateParam | None:
        for p in self.params:
            if p.name == name:
                return p
        return None


# ---------------------------------------------------------------------------
# Template object
# ---------------------------------------------------------------------------

@dataclass
class Template:
    """A complete template: metadata + raw TeX body."""
    meta: TemplateMeta
    tex_body: str
    source_path: Path | None = None

    def render_frame(self, param_values: dict[str, Any]) -> str:
        """Substitute all parameters into the TeX body for one frame.

        Placeholders use the syntax  {{{ PARAMNAME }}}  which is
        intentionally distinct from both LaTeX braces and standard Jinja.
        """
        result = self.tex_body
        for p in self.meta.params:
            placeholder = "{{{ " + p.name + " }}}"
            value = param_values.get(p.name, p.default)
            if isinstance(value, float):
                formatted = f"{value:.6f}".rstrip("0").rstrip(".")
            else:
                formatted = str(value)
            result = result.replace(placeholder, formatted)
        return result

    def generate_all_frames(
        self,
        overrides: dict[str, Any] | None = None,
        n_frames: int | None = None,
    ) -> Iterator[tuple[int, dict[str, Any], str]]:
        """Yield (index, param_dict, tex_source) for every frame."""
        overrides = overrides or {}
        sweep = self.meta.sweep_params
        if not sweep:
            vals = {p.name: overrides.get(p.name, p.default)
                    for p in self.meta.params}
            yield (0, vals, self.render_frame(vals))
            return
        sp = sweep[0]
        frame_count = n_frames or self.meta.recommended_frames
        sweep_vals = sp.sweep_values(frame_count)
        for idx, sv in enumerate(sweep_vals):
            vals: dict[str, Any] = {}
            for p in self.meta.params:
                if p.name == sp.name:
                    vals[p.name] = sv
                else:
                    vals[p.name] = overrides.get(p.name, p.default)
            yield (idx, vals, self.render_frame(vals))


# ---------------------------------------------------------------------------
# YAML header parser
# ---------------------------------------------------------------------------

_META_START = re.compile(r"^%%---\s*TIKZGIF\s+META\s*---\s*$", re.MULTILINE)
_META_END = re.compile(r"^%%---\s*END\s+META\s*---\s*$", re.MULTILINE)


def _parse_param(raw: dict) -> TemplateParam:
    ptype = ParamType(raw.get("type", "float"))
    return TemplateParam(
        name=raw["name"],
        param_type=ptype,
        default=raw.get("default", 0.0),
        minimum=raw.get("min"),
        maximum=raw.get("max"),
        step=raw.get("step"),
        choices=raw.get("choices"),
        description=raw.get("description", ""),
        is_sweep=raw.get("sweep", False),
        unit=raw.get("unit", ""),
    )


def parse_template(tex_source: str, source_path: Path | None = None) -> Template:
    """Parse a template .tex file into a Template object."""
    m_start = _META_START.search(tex_source)
    m_end = _META_END.search(tex_source)
    if not m_start or not m_end:
        raise ValueError(
            "Template is missing "
            "%%--- TIKZGIF META --- / %%--- END META --- delimiters."
        )
    yaml_block = tex_source[m_start.end():m_end.start()]
    yaml_lines = []
    for line in yaml_block.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("%%"):
            stripped = stripped[2:]
        elif stripped.startswith("%"):
            stripped = stripped[1:]
        yaml_lines.append(stripped)
    yaml_text = "\n".join(yaml_lines)
    data = yaml.safe_load(yaml_text) or {}
    params = [_parse_param(p) for p in data.get("params", [])]
    meta = TemplateMeta(
        name=data.get("name", "unnamed"),
        title=data.get("title", ""),
        description=data.get("description", ""),
        author=data.get("author", ""),
        version=data.get("version", "1.0.0"),
        domain=data.get("domain", ""),
        tags=data.get("tags", []),
        tikz_libraries=data.get("tikz_libraries", []),
        latex_packages=data.get("latex_packages", []),
        engine=data.get("engine", "pdflatex"),
        params=params,
        recommended_fps=data.get("fps", 15),
        recommended_frames=data.get("frames", 30),
        loop=data.get("loop", True),
        bounce=data.get("bounce", False),
        extends=data.get("extends"),
    )
    tex_body = tex_source[m_end.end():].lstrip("\n")
    return Template(meta=meta, tex_body=tex_body, source_path=source_path)
