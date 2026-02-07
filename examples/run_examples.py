"""
Run all example .tex files through tikzgif.

Usage:
    python examples/run_examples.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXAMPLES_DIR = Path(__file__).parent


def main() -> None:
    examples = [
        ("rotating_square.tex", "t", 0.0, 360.0, 36),
        ("sine_wave.tex", "t", 0.0, 6.2832, 30),
    ]

    for filename, param, start, stop, steps in examples:
        tex = EXAMPLES_DIR / filename
        gif = EXAMPLES_DIR / tex.with_suffix(".gif").name
        print(f"Rendering {filename} -> {gif.name}")
        cmd = [
            sys.executable, "-m", "tikzgif",
            "render", str(tex),
            "-p", param,
            "--start", str(start),
            "--stop", str(stop),
            "--steps", str(steps),
            "-o", str(gif),
            "--dpi", "150",
        ]
        subprocess.run(cmd, check=True)
        print(f"  Done: {gif}")


if __name__ == "__main__":
    main()
