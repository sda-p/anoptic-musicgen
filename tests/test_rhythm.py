import random

from musicgen.gen.rhythm import euclid, rough_cell
from musicgen.ir import Meter


def test_euclid_known_patterns():
    assert euclid(3, 8) == (0, 3, 6)          # tresillo
    assert euclid(4, 16) == (0, 4, 8, 12)     # four on the floor
    assert euclid(5, 16) == (0, 4, 7, 10, 13)


def test_euclid_rotation_and_bounds():
    assert euclid(3, 8, rotation=1) == (1, 4, 7)
    assert euclid(0, 8) == ()
    assert euclid(9, 8) == tuple(range(8))  # k clamped to n


def test_rough_cell_stays_in_bar_and_ordered():
    for seed in range(30):
        cell = rough_cell(random.Random(seed), density=0.5, roughness=0.4)
        assert len(cell) >= 2
        for (s, d), (s2, _) in zip(cell, cell[1:]):
            assert s + d <= s2, "notes must not overlap"
        assert all(s + d <= 16 for s, d in cell)
        assert all(d >= 1 for _, d in cell)


def test_roughness_merges_and_density_drops():
    smooth = [len(rough_cell(random.Random(s), 0.9, 0.0)) for s in range(40)]
    rough = [len(rough_cell(random.Random(s), 0.9, 0.8)) for s in range(40)]
    assert sum(rough) < sum(smooth), "roughness should merge notes away"
    sparse = [len(rough_cell(random.Random(s), 0.15, 0.0)) for s in range(40)]
    assert sum(sparse) < sum(smooth), "low density should drop notes"


def test_metric_weights_4_4():
    weights = Meter(4, 4).metric_weights()
    assert len(weights) == 16
    assert weights[0] == 4.0
    assert weights[8] == 3.5          # mid-bar (beat 3)
    assert weights[4] == weights[12] == 3.0
    assert weights[2] == 2.0          # 8th offbeat
    assert weights[1] == 1.0          # 16th offbeat
    assert Meter(4, 4).strong_slots() == (0, 4, 8, 12)


def test_metric_weights_3_4():
    weights = Meter(3, 4).metric_weights()
    assert len(weights) == 12
    assert weights[0] == 4.0
    assert weights[4] == weights[8] == 3.0  # no mid-bar in odd meters
    assert Meter(3, 4).strong_slots() == (0, 4, 8)
