"""
Bounding-box normalization.

THE CRITICAL PROBLEM
--------------------
In an animation, each frame may contain geometry of different extent.
For example, a growing spiral will produce a different bounding box at
frame 1 vs. frame 100.  If each frame's PDF has a different page size,
the resulting GIF will "jitter" -- the image shifts because the canvas
size changes frame-to-frame.

This module implements three strategies for solving this problem.


STRATEGY 1: Two-Pass Compilation (RECOMMENDED DEFAULT)
------------------------------------------------------
Pass 1 ("probe"):  Compile a sampled subset of frames WITHOUT a forced
                    bounding box.  Extract each frame's natural bounding
                    box from its PDF.  Compute the union (envelope) of
                    all boxes.

Pass 2 ("final"):  Re-generate every frame's .tex with a
                    \\useasboundingbox command set to the padded envelope.
                    Recompile.  Every frame now has an identical page size.

Pros:
  - Fully automatic.  Handles any TikZ content.
  - The probe pass uses smart sampling (first, last, evenly spaced) so it
    is O(1) relative to total frame count, not O(N).
  - Cached probe results carry over across builds.

Cons:
  - Doubles compilation time on first build for the probed subset.
  - Mitigated by caching: probe PDFs are cached, and if only the parameter
    range changes, many probes may already be cached.


STRATEGY 2: Post-Process PDF Page Sizes
-----------------------------------------
Compile all frames once.  Use a PDF manipulation tool (ghostscript,
PyMuPDF) to set every page to the size of the largest page.

Pros:  Single compilation pass.
Cons:  Requires an external tool.  Content centering may not match the
       TikZ coordinate origin, causing apparent object drift.


STRATEGY 3: User-Specified Bounding Box
-----------------------------------------
Require the user to include \\useasboundingbox in their template.
If all compiled frames have the same page size, accept them as-is.
Otherwise emit a clear diagnostic.

Pros:  Zero overhead.  Full user control.
Cons:  Puts burden on the user.


RECOMMENDATION
--------------
Strategy 1 (two-pass) is the default because it is fully automatic and
produces pixel-perfect results at acceptable cost.  When the user's
template already contains \\useasboundingbox, the probe pass is skipped
entirely (Strategy 3 becomes implicit).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tikzgif.exceptions import BoundingBoxError
from tikzgif.types import BoundingBox


# ---------------------------------------------------------------------------
# PDF bounding-box extraction
# ---------------------------------------------------------------------------

def extract_bbox_from_pdf(pdf_path: Path) -> BoundingBox:
    """
    Extract the page bounding box from a single-page PDF.

    Uses Ghostscript's bbox device first (most accurate), then falls
    back to parsing the PDF's MediaBox entry directly.

    Parameters
    ----------
    pdf_path : Path
        Path to a single-page PDF file.

    Returns
    -------
    BoundingBox

    Raises
    ------
    BoundingBoxError
        If the bounding box cannot be determined.
    """
    # --- Attempt 1: Ghostscript bbox device (most accurate) ---------------
    try:
        result = subprocess.run(
            [
                "gs",
                "-dBATCH", "-dNOPAUSE", "-dQUIET",
                "-sDEVICE=bbox",
                str(pdf_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # The bbox device writes to stderr.
        output = result.stderr
        m = re.search(
            r"%%HiResBoundingBox:\s+"
            r"(?P<xmin>[\d.]+)\s+(?P<ymin>[\d.]+)\s+"
            r"(?P<xmax>[\d.]+)\s+(?P<ymax>[\d.]+)",
            output,
        )
        if m:
            return BoundingBox(
                x_min=float(m.group("xmin")),
                y_min=float(m.group("ymin")),
                x_max=float(m.group("xmax")),
                y_max=float(m.group("ymax")),
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Ghostscript not available; try fallback.

    # --- Attempt 2: PyMuPDF (fitz) ----------------------------------------
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
        pass  # PyMuPDF not available or failed; try raw parse.

    # --- Attempt 3: Parse MediaBox from raw PDF bytes ---------------------
    try:
        raw = pdf_path.read_bytes()
        text = raw.decode("latin-1")
        m = re.search(
            r"/MediaBox\s*\[\s*"
            r"(?P<xmin>[-\d.]+)\s+(?P<ymin>[-\d.]+)\s+"
            r"(?P<xmax>[-\d.]+)\s+(?P<ymax>[-\d.]+)\s*\]",
            text,
        )
        if m:
            return BoundingBox(
                x_min=float(m.group("xmin")),
                y_min=float(m.group("ymin")),
                x_max=float(m.group("xmax")),
                y_max=float(m.group("ymax")),
            )
    except Exception:
        pass

    raise BoundingBoxError(
        f"Could not extract bounding box from {pdf_path}.  "
        f"Ensure the PDF was compiled successfully and is not empty."
    )


# ---------------------------------------------------------------------------
# Probe sampling
# ---------------------------------------------------------------------------

def select_probe_indices(total_frames: int, max_probes: int = 10) -> list[int]:
    """
    Choose a subset of frame indices to probe for bounding boxes.

    Always includes the first and last frame.  Fills in evenly spaced
    frames up to max_probes.

    For animations where geometry changes monotonically (e.g., a growing
    circle), the extremes are typically at the endpoints.  For oscillating
    geometry (e.g., a pendulum), intermediate samples catch the extremes.

    Parameters
    ----------
    total_frames : int
        Total number of frames in the animation.
    max_probes : int
        Maximum number of frames to probe.

    Returns
    -------
    list[int]
        Sorted, deduplicated list of 0-based frame indices.
    """
    if total_frames <= 0:
        return []
    if total_frames <= max_probes:
        return list(range(total_frames))

    indices: set[int] = set()
    indices.add(0)
    indices.add(total_frames - 1)

    # Fill remaining slots with evenly spaced indices.
    remaining = max_probes - 2
    if remaining > 0:
        step = (total_frames - 1) / (remaining + 1)
        for i in range(1, remaining + 1):
            indices.add(round(i * step))

    return sorted(indices)


def compute_envelope(bboxes: list[BoundingBox]) -> BoundingBox:
    """Compute the union of all bounding boxes."""
    if not bboxes:
        raise ValueError("Cannot compute envelope of zero bounding boxes.")
    result = bboxes[0]
    for box in bboxes[1:]:
        result = result.union(box)
    return result


# ---------------------------------------------------------------------------
# Consistency check
# ---------------------------------------------------------------------------

def check_bbox_consistency(
    bboxes: dict[int, BoundingBox],
    tolerance_bp: float = 1.0,
) -> tuple[bool, str]:
    """
    Check whether all bounding boxes are approximately the same size.

    Parameters
    ----------
    bboxes : dict[int, BoundingBox]
        Mapping from frame index to its bounding box.
    tolerance_bp : float
        Maximum allowed deviation in any dimension (in TeX points).

    Returns
    -------
    (consistent, message)
        consistent is True if all boxes are within tolerance.
        message describes the inconsistency if any.
    """
    if not bboxes:
        return True, "No bounding boxes to check."

    widths = {i: b.width for i, b in bboxes.items()}
    heights = {i: b.height for i, b in bboxes.items()}

    w_range = max(widths.values()) - min(widths.values())
    h_range = max(heights.values()) - min(heights.values())

    if w_range <= tolerance_bp and h_range <= tolerance_bp:
        return True, "All frames have consistent bounding boxes."

    # Find the most extreme frames for a helpful error message.
    min_w_frame = min(widths, key=widths.get)  # type: ignore[arg-type]
    max_w_frame = max(widths, key=widths.get)  # type: ignore[arg-type]
    min_h_frame = min(heights, key=heights.get)  # type: ignore[arg-type]
    max_h_frame = max(heights, key=heights.get)  # type: ignore[arg-type]

    msg = (
        f"Bounding boxes are inconsistent across frames.\n"
        f"  Width  range: {w_range:.1f}bp "
        f"(frame {min_w_frame}: {widths[min_w_frame]:.1f}bp, "
        f"frame {max_w_frame}: {widths[max_w_frame]:.1f}bp)\n"
        f"  Height range: {h_range:.1f}bp "
        f"(frame {min_h_frame}: {heights[min_h_frame]:.1f}bp, "
        f"frame {max_h_frame}: {heights[max_h_frame]:.1f}bp)\n"
        f"The two-pass strategy will enforce a uniform bounding box "
        f"automatically.  Alternatively, add \\useasboundingbox to your "
        f"template to control this manually."
    )
    return False, msg
