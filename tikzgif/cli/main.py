"""Main CLI entry point for tikzgif."""

from __future__ import annotations

import argparse
import sys

from .render_cli import build_render_parser
from .templates_cli import build_templates_parser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tikzgif",
        description="Parameterized TikZ to animated GIF pipeline",
    )
    parser.add_argument("--version", action="version", version="tikzgif 0.1.0")
    subparsers = parser.add_subparsers(dest="command")
    build_render_parser(subparsers)
    build_templates_parser(subparsers)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "render":
        return args.func(args)
    if args.command == "templates":
        if not hasattr(args, "func") or args.func is None:
            subparsers.choices["templates"].print_help()
            return 0
        return args.func(args)
    parser.print_help()
    return 0


def cli_entry() -> None:
    sys.exit(main())
