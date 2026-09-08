"""
Unit tests for tm_helpers.py utility functions.
"""

import pytest
from tm_helpers import calc_blind_hole_depth_mm


class TestCalcBlindHoleDepthMm:
    """Test calc_blind_hole_depth_mm function."""

    def test_standard_m3_insert(self):
        """M3 standard: 5.7mm insert + 1.0mm extra = 6.7mm."""
        assert calc_blind_hole_depth_mm(5.7, 1.0) == pytest.approx(6.7)

    def test_with_chamfer_added(self):
        """Chamfer size is added on top of insert length and extra depth."""
        assert calc_blind_hole_depth_mm(5.7, 1.0, 0.5) == pytest.approx(7.2)

    def test_zero_extra_depth(self):
        """Zero extra depth returns the insert length."""
        assert calc_blind_hole_depth_mm(5.7, 0.0) == pytest.approx(5.7)

    def test_m10_insert(self):
        """M10: 12.7mm insert + 1.0mm extra + 0.5mm chamfer = 14.2mm."""
        assert calc_blind_hole_depth_mm(12.7, 1.0, 0.5) == pytest.approx(14.2)

    def test_chamfer_defaults_to_zero(self):
        """Omitting the chamfer argument must not change the result."""
        assert calc_blind_hole_depth_mm(8.1, 1.0) == calc_blind_hole_depth_mm(8.1, 1.0, 0.0)
