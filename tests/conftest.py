"""
Shared fixtures for the tikzgif test suite.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from PIL import Image


def pytest_configure(config):
    """Register custom markers used across sub-suites."""
    config.addinivalue_line("markers", "benchmark: performance benchmark test")


@pytest.fixture(scope="session")
def has_pdflatex() -> bool:
    return shutil.which("pdflatex") is not None


@pytest.fixture(scope="session")
def has_lualatex() -> bool:
    return shutil.which("lualatex") is not None


@pytest.fixture(scope="session")
def has_tikzgif() -> bool:
    return shutil.which("tikzgif") is not None


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory(prefix="tikzgif_test_") as d:
        yield Path(d)


@pytest.fixture
def sample_rgba_frame():
    """A 200x200 RGBA frame with a red square on white background."""
    img = Image.new("RGBA", (200, 200), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            img.putpixel((x, y), (255, 0, 0, 255))
    return img


@pytest.fixture
def sample_frame_sequence():
    """A sequence of 10 frames with varying content."""
    frames = []
    for i in range(10):
        img = Image.new("RGBA", (100, 100), "white")
        # Draw a dot that moves across the frame
        cx = 10 + i * 8
        cy = 50
        for x in range(cx - 5, cx + 5):
            for y in range(cy - 5, cy + 5):
                if 0 <= x < 100 and 0 <= y < 100:
                    img.putpixel((x, y), (0, 0, 0, 255))
        frames.append(img)
    return frames
