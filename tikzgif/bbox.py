"""Bounding-box extraction utilities."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tikzgif.exceptions import BoundingBoxError
from tikzgif.types import BoundingBox


def extract_bbox_from_pdf(pdf_path: Path) -> BoundingBox:
    """Extract page bounds from a single-page PDF."""

    try:
        result = subprocess.run(
            [
                "gs",
                "-dBATCH",
                "-dNOPAUSE",
                "-dQUIET",
                "-sDEVICE=bbox",
                str(pdf_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        match = re.search(
            r"%%HiResBoundingBox:\s+"
            r"(?P<xmin>[\d.]+)\s+(?P<ymin>[\d.]+)\s+"
            r"(?P<xmax>[\d.]+)\s+(?P<ymax>[\d.]+)",
            result.stderr,
        )
        if match:
            return BoundingBox(
                x_min=float(match.group("xmin")),
                y_min=float(match.group("ymin")),
                x_max=float(match.group("xmax")),
                y_max=float(match.group("ymax")),
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        import fitz  # type: ignore[import-untyped]

        doc = fitz.open(str(pdf_path))
        page = doc[0]
        rect = page.mediabox
        doc.close()
        return BoundingBox(
            x_min=float(rect.x0),
            y_min=float(rect.y0),
            x_max=float(rect.x1),
            y_max=float(rect.y1),
        )
    except Exception:
        pass

    try:
        text = pdf_path.read_bytes().decode("latin-1")
        match = re.search(
            r"/MediaBox\s*\[\s*"
            r"(?P<xmin>[-\d.]+)\s+(?P<ymin>[-\d.]+)\s+"
            r"(?P<xmax>[-\d.]+)\s+(?P<ymax>[-\d.]+)\s*\]",
            text,
        )
        if match:
            return BoundingBox(
                x_min=float(match.group("xmin")),
                y_min=float(match.group("ymin")),
                x_max=float(match.group("xmax")),
                y_max=float(match.group("ymax")),
            )
    except Exception:
        pass

    raise BoundingBoxError(
        f"Could not extract bounding box from {pdf_path}. "
        "Ensure the PDF was compiled successfully and is not empty."
    )
