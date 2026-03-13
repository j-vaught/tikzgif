"""Template parsing and frame-spec generation stage."""

from .parser import (
    DEFAULT_PARAM_TOKEN,
    ParsedTemplate,
    generate_frame_specs,
    parse_template,
    parse_template_from_file,
)

__all__ = [
    "DEFAULT_PARAM_TOKEN",
    "ParsedTemplate",
    "parse_template",
    "parse_template_from_file",
    "generate_frame_specs",
]
