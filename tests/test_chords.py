import pytest

from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale

C_IONIAN = Scale(0, "ionian")
C_AEOLIAN = Scale(0, "aeolian")


def test_triad_pitch_classes():
    assert Chord(1).pitch_classes(C_IONIAN) == (0, 4, 7)    # C E G
    assert Chord(2).pitch_classes(C_IONIAN) == (2, 5, 9)    # D F A
    assert Chord(5).pitch_classes(C_IONIAN) == (7, 11, 2)   # G B D


def test_seventh_and_ninth():
    assert Chord(5, ("7",)).pitch_classes(C_IONIAN) == (7, 11, 2, 5)
    assert Chord(1, ("9",)).pitch_classes(C_IONIAN) == (0, 4, 7, 2)
    assert Chord(5, ("7", "9")).pitch_classes(C_IONIAN) == (7, 11, 2, 5, 9)


def test_sus_chords():
    assert Chord(1, ("sus4",)).pitch_classes(C_IONIAN) == (0, 5, 7)
    assert Chord(1, ("sus2",)).pitch_classes(C_IONIAN) == (0, 2, 7)
    assert Chord(1, ("sus4",)).quality(C_IONIAN) == "sus"


def test_qualities_follow_mode():
    assert Chord(1).quality(C_IONIAN) == "maj"
    assert Chord(2).quality(C_IONIAN) == "min"
    assert Chord(7).quality(C_IONIAN) == "dim"
    assert Chord(1).quality(C_AEOLIAN) == "min"
    assert Chord(7).quality(C_AEOLIAN) == "maj"  # bVII, the modal dominant


def test_symbols_ionian():
    symbols = [Chord(d).symbol(C_IONIAN) for d in range(1, 8)]
    assert symbols == ["I", "ii", "iii", "IV", "V", "vi", "vii°"]


def test_symbols_aeolian():
    symbols = [Chord(d).symbol(C_AEOLIAN) for d in range(1, 8)]
    assert symbols == ["i", "ii°", "III", "iv", "v", "VI", "VII"]


def test_extension_symbols():
    assert Chord(5, ("7",)).symbol(C_IONIAN) == "V7"
    assert Chord(5, ("7", "9")).symbol(C_IONIAN) == "V9"
    assert Chord(1, ("9",)).symbol(C_IONIAN) == "I(add9)"
    assert Chord(1, ("sus4",)).symbol(C_IONIAN) == "Isus4"


def test_applied_dominants():
    # secondary dominants: a major-minor 7th a fifth above the target, chromatic
    v_of_vi = Chord.applied_dominant(6)   # E7 = E G# B D (G# is chromatic in C major)
    assert v_of_vi.pitch_classes(C_IONIAN) == (4, 8, 11, 2)
    assert v_of_vi.symbol(C_IONIAN) == "V7/vi"
    assert v_of_vi.function == "D"        # functions as a dominant, not its nominal degree
    assert v_of_vi.applied == 6
    v_of_V = Chord.applied_dominant(5)    # D7 = D F# A C
    assert v_of_V.pitch_classes(C_IONIAN) == (2, 6, 9, 0)
    assert v_of_V.symbol(C_IONIAN) == "V7/V"
    # triad-only form, and an uppercase target keeps its case (V/IV)
    assert Chord.applied_dominant(4, seventh=False).pitch_classes(C_IONIAN) == (0, 4, 7)
    assert Chord.applied_dominant(4).symbol(C_IONIAN) == "V7/IV"


def test_applied_and_source_mode_mutually_exclusive():
    with pytest.raises(ValueError):
        Chord(3, applied=6, source_mode="aeolian")


def test_borrowed_chords():
    iv = Chord(4, source_mode="aeolian")
    assert iv.pitch_classes(C_IONIAN) == (5, 8, 0)  # F Ab C
    assert iv.symbol(C_IONIAN) == "iv"
    flat_six = Chord(6, source_mode="aeolian")
    assert flat_six.pitch_classes(C_IONIAN) == (8, 0, 3)  # Ab C Eb
    assert flat_six.symbol(C_IONIAN) == "bVI"
    assert flat_six.quality(C_IONIAN) == "maj"


def test_inversion():
    first_inv = Chord(1, inversion=1)
    assert first_inv.bass_pc(C_IONIAN) == 4
    assert first_inv.voiced_pcs(C_IONIAN) == (4, 7, 0)
    assert first_inv.symbol(C_IONIAN) == "I6"
    assert Chord(1, inversion=2).symbol(C_IONIAN) == "I64"
    assert Chord(5, extensions=("7",), inversion=1).symbol(C_IONIAN) == "V65"


def test_function():
    assert Chord(1).function == "T"
    assert Chord(4).function == "PD"
    assert Chord(5).function == "D"
    assert Chord(6, source_mode="aeolian").function == "T"  # bVI substitutes for vi


def test_invalid_chords_raise():
    with pytest.raises(ValueError):
        Chord(0)
    with pytest.raises(ValueError):
        Chord(1, ("13",))
    with pytest.raises(ValueError):
        Chord(1, ("sus2", "sus4"))
    with pytest.raises(ValueError):
        Chord(1, inversion=3)  # triad has 3 members
    with pytest.raises(ValueError):
        Chord(1, source_mode="klingon")
