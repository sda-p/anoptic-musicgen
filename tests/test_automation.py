import pytest

from musicgen.control.automation import affect_at

CURVE = [
    (0, {"valence": 0.0, "energy": 0.0, "tension": 0.0}),
    (10, {"valence": 1.0, "energy": 0.5, "tension": 1.0}),
    (20, {"valence": 1.0, "energy": 1.0, "tension": 0.0}),
]


def test_breakpoints_exact():
    assert affect_at(CURVE, 0) == {"valence": 0.0, "energy": 0.0, "tension": 0.0}
    assert affect_at(CURVE, 10) == {"valence": 1.0, "energy": 0.5, "tension": 1.0}


def test_linear_interpolation():
    mid = affect_at(CURVE, 5)
    assert mid == {"valence": 0.5, "energy": 0.25, "tension": 0.5}
    late = affect_at(CURVE, 15)
    assert late == {"valence": 1.0, "energy": 0.75, "tension": 0.5}


def test_clamped_outside_range():
    assert affect_at(CURVE, -5) == affect_at(CURVE, 0)
    assert affect_at(CURVE, 99) == affect_at(CURVE, 20)


def test_incomplete_breakpoint_rejected():
    with pytest.raises(ValueError):
        affect_at([(0, {"valence": 0.0})], 0)
    with pytest.raises(ValueError):
        affect_at([], 0)
