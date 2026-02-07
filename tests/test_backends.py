"""
Tests for the backend detection and conversion pipeline.

These tests use synthetic PDF-like inputs where possible. Tests that
require real external tools (pdftoppm, gs, etc.) are marked with
pytest.mark.skipif so the suite runs cleanly on any machine.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from tikzgif.backends import (
    BACKEND_PRIORITY,
    ColorSpace,
    ConversionBackend,
    GhostscriptBackend,
    ImageMagickBackend,
    Pdf2ImageBackend,
    PdftoppmBackend,
    PyMuPDFBackend,
    RenderConfig,
    get_backend_by_name,
)
from tikzgif.detection import (
    probe_system,
    print_diagnostics,
    select_backend,
)


# ---------------------------------------------------------------------------
# RenderConfig tests
# ---------------------------------------------------------------------------

class TestRenderConfig:
    def test_default_dpi(self):
        cfg = RenderConfig()
        assert cfg.dpi == 300

    def test_render_dpi_without_aa(self):
        cfg = RenderConfig(antialias=False)
        assert cfg.render_dpi == cfg.dpi

    def test_render_dpi_with_aa_factor(self):
        cfg = RenderConfig(dpi=150, antialias=True, antialias_factor=2)
        assert cfg.render_dpi == 300

    def test_pixel_dimensions(self):
        cfg = RenderConfig(dpi=72)
        w, h = cfg.pixel_dimensions(612, 792)
        assert w == 612
        assert h == 792

    def test_pixel_dimensions_300dpi(self):
        cfg = RenderConfig(dpi=300)
        w, h = cfg.pixel_dimensions(360, 360)  # 5 inch square
        assert w == 1500
        assert h == 1500


# ---------------------------------------------------------------------------
# Backend availability and install hints
# ---------------------------------------------------------------------------

class TestBackendAvailability:
    """Test that each backend correctly reports availability."""

    def test_priority_list_not_empty(self):
        assert len(BACKEND_PRIORITY) == 5

    def test_all_backends_have_names(self):
        for cls in BACKEND_PRIORITY:
            assert hasattr(cls, "name")
            assert isinstance(cls.name, str)
            assert len(cls.name) > 0

    def test_all_backends_have_install_hint(self):
        for cls in BACKEND_PRIORITY:
            hint = cls.install_hint()
            assert isinstance(hint, str)
            assert len(hint) > 0

    def test_pdftoppm_availability_matches_which(self):
        expected = shutil.which("pdftoppm") is not None
        assert PdftoppmBackend.is_available() == expected

    def test_ghostscript_availability(self):
        has_gs = any(
            shutil.which(n) is not None
            for n in ("gs", "gswin64c", "gswin32c")
        )
        assert GhostscriptBackend.is_available() == has_gs


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

class TestBackendSelection:
    def test_select_returns_backend_instance(self):
        """At least one backend should be available in most environments."""
        try:
            backend = select_backend()
            assert isinstance(backend, ConversionBackend)
        except RuntimeError:
            pytest.skip("No backend available on this system.")

    def test_select_preferred_invalid_name(self):
        """Requesting an unknown name should still fall back."""
        try:
            backend = select_backend(preferred="nonexistent_backend")
            assert isinstance(backend, ConversionBackend)
        except RuntimeError:
            pytest.skip("No backend available.")

    def test_get_backend_by_name_unknown(self):
        with pytest.raises(ValueError, match="Unknown backend"):
            get_backend_by_name("does_not_exist")


# ---------------------------------------------------------------------------
# System probe
# ---------------------------------------------------------------------------

class TestSystemProbe:
    def test_probe_returns_dict(self):
        probes = probe_system()
        assert isinstance(probes, dict)
        assert "pdftoppm" in probes
        assert "ghostscript" in probes
        assert "pillow" in probes

    def test_diagnostics_string(self):
        report = print_diagnostics()
        assert "tikzgif backend diagnostics" in report
        assert "Platform:" in report


# ---------------------------------------------------------------------------
# Ensure RGBA normalization
# ---------------------------------------------------------------------------

class TestEnsureRGBA:
    def test_rgb_to_rgba(self):
        img = Image.new("RGB", (10, 10), "red")
        result = ConversionBackend._ensure_rgba(img, None)
        assert result.mode == "RGBA"

    def test_rgba_with_background(self):
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
        result = ConversionBackend._ensure_rgba(img, "white")
        assert result.mode == "RGBA"
        # The alpha should be composited onto white.

    def test_grayscale_to_rgba(self):
        img = Image.new("L", (10, 10), 128)
        result = ConversionBackend._ensure_rgba(img, None)
        assert result.mode == "RGBA"


# ---------------------------------------------------------------------------
# Downscale AA helper
# ---------------------------------------------------------------------------

class TestDownscaleAA:
    def test_no_op_when_equal(self):
        img = Image.new("RGBA", (100, 100), "red")
        result = ConversionBackend._downscale_aa(img, 300, 300)
        assert result.size == (100, 100)

    def test_downscale_2x(self):
        img = Image.new("RGBA", (200, 200), "red")
        result = ConversionBackend._downscale_aa(img, 150, 300)
        assert result.size == (100, 100)
