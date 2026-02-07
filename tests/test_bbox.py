"""
Tests for bounding-box utilities.
"""

import pytest

from tikzgif.bbox import (
    check_bbox_consistency,
    compute_envelope,
    select_probe_indices,
)
from tikzgif.types import BoundingBox


class TestBoundingBox:
    def test_width_height(self):
        bb = BoundingBox(10, 20, 110, 220)
        assert bb.width == 100
        assert bb.height == 200

    def test_union(self):
        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(-5, 5, 15, 8)
        u = a.union(b)
        assert u.x_min == -5
        assert u.y_min == 0
        assert u.x_max == 15
        assert u.y_max == 10

    def test_padded(self):
        bb = BoundingBox(0, 0, 10, 10)
        p = bb.padded(3.0)
        assert p.x_min == -3.0
        assert p.y_min == -3.0
        assert p.x_max == 13.0
        assert p.y_max == 13.0

    def test_to_tikz_clip(self):
        bb = BoundingBox(-5.0, -3.0, 5.0, 3.0)
        cmd = bb.to_tikz_clip()
        assert r"\useasboundingbox" in cmd
        assert "-5.0bp" in cmd
        assert "5.0bp" in cmd


class TestSelectProbeIndices:
    def test_small_frame_count(self):
        indices = select_probe_indices(5, max_probes=10)
        assert indices == [0, 1, 2, 3, 4]

    def test_includes_first_and_last(self):
        indices = select_probe_indices(100, max_probes=5)
        assert 0 in indices
        assert 99 in indices

    def test_correct_count(self):
        indices = select_probe_indices(200, max_probes=10)
        assert len(indices) == 10

    def test_sorted(self):
        indices = select_probe_indices(500, max_probes=8)
        assert indices == sorted(indices)

    def test_single_frame(self):
        indices = select_probe_indices(1, max_probes=10)
        assert indices == [0]

    def test_zero_frames(self):
        indices = select_probe_indices(0, max_probes=10)
        assert indices == []


class TestComputeEnvelope:
    def test_single_box(self):
        bb = BoundingBox(0, 0, 10, 10)
        assert compute_envelope([bb]) == bb

    def test_multiple_boxes(self):
        boxes = [
            BoundingBox(0, 0, 10, 10),
            BoundingBox(-5, -5, 8, 8),
            BoundingBox(2, 2, 15, 12),
        ]
        env = compute_envelope(boxes)
        assert env.x_min == -5
        assert env.y_min == -5
        assert env.x_max == 15
        assert env.y_max == 12

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_envelope([])


class TestCheckBboxConsistency:
    def test_consistent(self):
        bboxes = {
            0: BoundingBox(0, 0, 100, 100),
            1: BoundingBox(0, 0, 100.5, 100),
            2: BoundingBox(0, 0, 100, 100.5),
        }
        ok, msg = check_bbox_consistency(bboxes, tolerance_bp=1.0)
        assert ok

    def test_inconsistent(self):
        bboxes = {
            0: BoundingBox(0, 0, 50, 50),
            1: BoundingBox(0, 0, 100, 100),
        }
        ok, msg = check_bbox_consistency(bboxes, tolerance_bp=1.0)
        assert not ok
        assert "inconsistent" in msg.lower()

    def test_empty(self):
        ok, msg = check_bbox_consistency({})
        assert ok
