"""BEV transform tests."""
from alfred.vision.bev import BirdEyeView


def test_bev_init():
    bev = BirdEyeView()
    assert bev is not None


def test_bev_transform_uncalibrated_returns_none():
    bev = BirdEyeView()
    result = bev.transform(None)
    assert result is None


def test_bev_extract_path_empty():
    bev = BirdEyeView()
    result = bev.extract_path(None)
    assert result == []


def test_bev_fit_spline_few_points():
    import numpy as np
    bev = BirdEyeView()
    pts = [(0, 0), (1, 1)]
    result = bev.fit_spline(pts)
    assert len(result) == 2
