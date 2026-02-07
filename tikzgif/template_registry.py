"""
Template registry -- discovery, loading, and management of templates.

Templates are discovered from three sources (in priority order):
1. Built-in templates shipped with the tikzgif package
2. User template directories (TIKZGIF_TEMPLATE_PATH env var or ~/.config/tikzgif/templates/)
3. Project-local templates (./.tikzgif/templates/)
"""

from __future__ import annotations

import os
from pathlib import Path

from .template_schema import Template, TemplateMeta, parse_template


_BUILTIN_DIR = Path(__file__).parent / "templates"
_USER_CONFIG_DIR = Path.home() / ".config" / "tikzgif" / "templates"
_LOCAL_DIR_NAME = ".tikzgif/templates"


def _env_template_dirs() -> list[Path]:
    raw = os.environ.get("TIKZGIF_TEMPLATE_PATH", "")
    if not raw:
        return []
    return [Path(p) for p in raw.split(":") if p]


def template_search_dirs() -> list[Path]:
    dirs: list[Path] = []
    local = Path.cwd() / _LOCAL_DIR_NAME
    if local.is_dir():
        dirs.append(local)
    dirs.extend(d for d in _env_template_dirs() if d.is_dir())
    if _USER_CONFIG_DIR.is_dir():
        dirs.append(_USER_CONFIG_DIR)
    dirs.append(_BUILTIN_DIR)
    return dirs


class TemplateRegistry:
    """Discovers, caches, and serves Template objects."""

    def __init__(self, extra_dirs: list[Path] | None = None) -> None:
        self._cache: dict[str, Template] = {}
        self._extra_dirs = extra_dirs or []
        self._scanned = False

    def _scan_dir(self, directory: Path) -> dict[str, Template]:
        found: dict[str, Template] = {}
        if not directory.is_dir():
            return found
        for tex_file in sorted(directory.rglob("*.tex")):
            if tex_file.name.startswith("."):
                continue
            try:
                raw = tex_file.read_text(encoding="utf-8")
                tpl = parse_template(raw, source_path=tex_file)
                found[tpl.meta.name] = tpl
            except Exception:
                continue
        return found

    def scan(self, force: bool = False) -> None:
        if self._scanned and not force:
            return
        self._cache.clear()
        search = template_search_dirs()
        for ed in reversed(self._extra_dirs):
            if ed.is_dir():
                search.insert(0, ed)
        for d in reversed(search):
            self._cache.update(self._scan_dir(d))
        self._scanned = True

    def list_templates(self, domain: str | None = None) -> list[TemplateMeta]:
        self.scan()
        metas = [t.meta for t in self._cache.values()]
        if domain:
            metas = [m for m in metas if m.domain == domain]
        return sorted(metas, key=lambda m: m.name)

    def get(self, name: str) -> Template:
        self.scan()
        if name not in self._cache:
            raise KeyError(
                f"Template '{name}' not found.  "
                f"Available: {', '.join(sorted(self._cache))}"
            )
        tpl = self._cache[name]
        if tpl.meta.extends:
            tpl = self._resolve_inheritance(tpl)
        return tpl

    def _resolve_inheritance(self, child: Template) -> Template:
        parent_name = child.meta.extends
        if parent_name is None or parent_name not in self._cache:
            return child
        parent = self._cache[parent_name]
        merged_params = {p.name: p for p in parent.meta.params}
        for p in child.meta.params:
            merged_params[p.name] = p
        merged_meta = TemplateMeta(
            name=child.meta.name,
            title=child.meta.title or parent.meta.title,
            description=child.meta.description or parent.meta.description,
            author=child.meta.author or parent.meta.author,
            version=child.meta.version,
            domain=child.meta.domain or parent.meta.domain,
            tags=list(set(parent.meta.tags + child.meta.tags)),
            tikz_libraries=list(set(
                parent.meta.tikz_libraries + child.meta.tikz_libraries
            )),
            latex_packages=list(set(
                parent.meta.latex_packages + child.meta.latex_packages
            )),
            engine=child.meta.engine or parent.meta.engine,
            params=list(merged_params.values()),
            recommended_fps=child.meta.recommended_fps,
            recommended_frames=child.meta.recommended_frames,
            loop=child.meta.loop,
            bounce=child.meta.bounce,
            extends=None,
        )
        merged_body = child.tex_body.replace(
            "{{{ PARENT_BODY }}}", parent.tex_body
        )
        return Template(
            meta=merged_meta, tex_body=merged_body, source_path=child.source_path
        )

    def register(self, template: Template) -> None:
        self.scan()  # ensure base scan has happened first
        self._cache[template.meta.name] = template

    def domains(self) -> list[str]:
        self.scan()
        return sorted(
            {t.meta.domain for t in self._cache.values() if t.meta.domain}
        )


_default_registry: TemplateRegistry | None = None


def get_registry() -> TemplateRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = TemplateRegistry()
    return _default_registry
