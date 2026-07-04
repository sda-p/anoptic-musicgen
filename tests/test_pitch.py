import pytest

from musicgen.theory.pitch import name_to_midi, octave_of, pitch_class, pitch_name


def test_midi_60_is_c4():
    assert pitch_name(60) == "C4"
    assert name_to_midi("C4") == 60
    assert octave_of(60) == 4
    assert pitch_class(60) == 0


def test_names_round_trip():
    for midi in range(0, 128):
        assert name_to_midi(pitch_name(midi)) == midi


def test_accidentals():
    assert pitch_name(61) == "C#4"
    assert pitch_name(61, prefer_flats=True) == "Db4"
    assert name_to_midi("Db4") == 61
    assert name_to_midi("Cb4") == 59   # enharmonic B3
    assert name_to_midi("B#3") == 60   # enharmonic C4


def test_bad_names_raise():
    for bad in ("H4", "C", "C##4", "Cb", "C444444"):
        with pytest.raises(ValueError):
            name_to_midi(bad)
