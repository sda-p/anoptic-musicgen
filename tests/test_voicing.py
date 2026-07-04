from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale
from musicgen.theory.voicing import VoicingConfig, select_voice_pcs, voice_chord

CFG = VoicingConfig()
C_IONIAN = Scale(0, "ionian")


def test_select_doubles_root_never_third():
    assert sorted(select_voice_pcs((0, 4, 7), 4)) == [0, 0, 4, 7]
    assert sorted(select_voice_pcs((0, 4, 7), 5)) == [0, 0, 4, 7, 7]


def test_select_drops_fifth_first():
    ninth = Chord(5, ("7", "9")).pitch_classes(C_IONIAN)  # (7, 11, 2, 5, 9)
    picked = select_voice_pcs(ninth, 4)
    assert sorted(picked) == sorted((7, 11, 5, 9))  # fifth (2) dropped


def test_seventh_chord_uses_all_members():
    assert sorted(select_voice_pcs((7, 11, 2, 5), 4)) == [2, 5, 7, 11]


def test_first_voicing_centered_and_ascending():
    voicing, _ = voice_chord((0, 4, 7), None, CFG)
    assert list(voicing) == sorted(set(voicing))
    assert all(CFG.lo <= p <= CFG.hi for p in voicing)
    center = sum(voicing) / len(voicing)
    assert abs(center - CFG.center) < 6


def test_progression_chain_moves_smoothly():
    degrees = [1, 4, 5, 6, 2, 5, 1, 6, 4, 5, 1]
    prev = None
    for degree in degrees:
        pcs = Chord(degree).pitch_classes(C_IONIAN)
        voicing, _ = voice_chord(pcs, prev, CFG)
        assert list(voicing) == sorted(set(voicing)), "ascending, no unisons"
        assert all(CFG.lo <= p <= CFG.hi for p in voicing)
        assert all(b - a <= CFG.max_adjacent_gap for a, b in zip(voicing, voicing[1:]))
        if prev is not None:
            moves = [abs(a - b) for a, b in zip(prev, voicing)]
            assert max(moves) <= 7, (prev, voicing)
        prev = voicing


def test_voicing_is_deterministic():
    a, _ = voice_chord((0, 4, 7), (55, 60, 64, 67), CFG)
    b, _ = voice_chord((0, 4, 7), (55, 60, 64, 67), CFG)
    assert a == b


def test_common_tones_hold():
    # I -> IV shares C: the C should not move.
    prev, _ = voice_chord((0, 4, 7), None, CFG)
    nxt, _ = voice_chord((5, 9, 0), prev, CFG)
    shared = set(prev) & set(nxt)
    assert any(p % 12 == 0 for p in shared)
