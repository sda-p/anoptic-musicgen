import pytest

from musicgen.theory.scales import BRIGHTNESS, Scale, mode_intervals


def test_c_ionian_pcs():
    assert Scale(0, "ionian").pcs == (0, 2, 4, 5, 7, 9, 11)


def test_relative_modes_share_pitch_content():
    c_ionian = set(Scale(0, "ionian").pcs)
    assert set(Scale(9, "aeolian").pcs) == c_ionian  # A aeolian
    assert set(Scale(2, "dorian").pcs) == c_ionian   # D dorian


def test_mode_intervals():
    assert mode_intervals("phrygian") == (0, 1, 3, 5, 7, 8, 10)
    assert mode_intervals("lydian") == (0, 2, 4, 6, 7, 9, 11)
    assert mode_intervals("aeolian") == (0, 2, 3, 5, 7, 8, 10)


def test_degree_of():
    scale = Scale(0, "ionian")
    assert scale.degree_of(64) == 3      # E4
    assert scale.degree_of(61) is None   # C#4 chromatic


def test_pitch_at():
    scale = Scale(0, "ionian")
    assert scale.pitch_at(1, 4) == 60   # C4
    assert scale.pitch_at(5, 3) == 55   # G3
    assert scale.pitch_at(8, 4) == 72   # degree wrap: C5
    a_aeolian = Scale(9, "aeolian")
    assert a_aeolian.pitch_at(1, 4) == 69  # A4


def test_stacked_thirds_across_octave_break():
    scale = Scale(0, "ionian")
    # V triad from degree 5: G4, B4, D5
    assert [scale.pitch_at(d, 4) for d in (5, 7, 9)] == [67, 71, 74]


def test_brightness_ordering():
    order = ("lydian", "ionian", "mixolydian", "dorian", "aeolian", "phrygian")
    values = [BRIGHTNESS[m] for m in order]
    assert values == sorted(values, reverse=True)
    assert "locrian" not in BRIGHTNESS


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        Scale(0, "klingon")
    with pytest.raises(ValueError):
        Scale(12, "ionian")
    with pytest.raises(ValueError):
        Scale(0, "ionian").pitch_at(0, 4)
