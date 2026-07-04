import pytest

from musicgen.ir import HarmonicContext, Meter, NoteEvent
from musicgen.theory.scales import Scale
from musicgen.verify import TheoryLintError, assert_clean, lint

METER = Meter(4, 4)
C_IONIAN = [HarmonicContext(bar=b, scale=Scale(0, "ionian"), chord_sym="I") for b in range(4)]


def _rules(violations):
    return [v.rule for v in violations]


def test_clean_events_pass():
    events = [
        NoteEvent(0.0, 1.0, 60, 80, "melody", degree=1),
        NoteEvent(1.0, 0.5, 67, 80, "melody", degree=5),
        NoteEvent(4.0, 4.0, 36, 90, "bass"),
    ]
    assert lint(events, C_IONIAN, METER) == []
    assert_clean(events, C_IONIAN, METER)  # must not raise


def test_out_of_scale_flagged():
    events = [NoteEvent(0.0, 1.0, 61, 80, "melody")]  # C#4 in C ionian
    assert _rules(lint(events, C_IONIAN, METER)) == ["scale"]
    with pytest.raises(TheoryLintError):
        assert_clean(events, C_IONIAN, METER)


def test_chromatic_role_licenses_out_of_scale():
    events = [NoteEvent(0.0, 1.0, 61, 80, "melody", role="approach")]
    assert lint(events, C_IONIAN, METER) == []


def test_perc_exempt_from_scale_rules():
    events = [NoteEvent(0.0, 0.25, 42, 80, "perc")]  # F#2 closed hat
    assert lint(events, C_IONIAN, METER) == []


def test_off_grid_flagged_pre_stage_only():
    events = [NoteEvent(0.3, 1.0, 60, 80, "melody")]
    assert "grid" in _rules(lint(events, C_IONIAN, METER, stage="pre"))
    assert "grid" not in _rules(lint(events, C_IONIAN, METER, stage="post"))


def test_wrong_degree_annotation_flagged():
    events = [NoteEvent(0.0, 1.0, 64, 80, "melody", degree=5)]  # E4 is ^3
    assert _rules(lint(events, C_IONIAN, METER)) == ["degree"]


def test_missing_context_flagged():
    events = [NoteEvent(16.0, 1.0, 60, 80, "melody")]  # bar 5 has no context
    assert _rules(lint(events, C_IONIAN, METER)) == ["context"]


def test_pad_voice_leap_flagged():
    events = [
        NoteEvent(0.0, 4.0, 60, 80, "pad"), NoteEvent(0.0, 4.0, 64, 80, "pad"),
        NoteEvent(4.0, 4.0, 72, 80, "pad"), NoteEvent(4.0, 4.0, 76, 80, "pad"),  # +12 each
    ]
    assert "voice-move" in _rules(lint(events, C_IONIAN, METER))


def test_pad_unison_doubling_flagged():
    events = [NoteEvent(0.0, 4.0, 60, 80, "pad"), NoteEvent(0.0, 4.0, 60, 80, "pad")]
    assert "unison" in _rules(lint(events, C_IONIAN, METER))


def test_pad_range_flagged():
    events = [NoteEvent(0.0, 4.0, 48, 80, "pad")]  # C3, below pad range
    assert "pad-range" in _rules(lint(events, C_IONIAN, METER))


def test_pad_nonchord_tone_flagged():
    ctx = [HarmonicContext(bar=0, scale=Scale(0, "ionian"), chord_sym="I", chord_pcs=(0, 4, 7))]
    good = [NoteEvent(0.0, 4.0, 60, 80, "pad"), NoteEvent(0.0, 4.0, 64, 80, "pad")]
    assert lint(good, ctx, METER) == []
    bad = [NoteEvent(0.0, 4.0, 62, 80, "pad")]  # D over C major
    assert "chord-tone" in _rules(lint(bad, ctx, METER))


def test_bass_root_rule():
    ctx = [HarmonicContext(bar=0, scale=Scale(0, "ionian"), chord_sym="I", chord_pcs=(0, 4, 7))]
    good = [NoteEvent(0.0, 4.0, 36, 90, "bass")]  # C2 on beat 1
    assert lint(good, ctx, METER) == []
    bad = [NoteEvent(0.0, 4.0, 43, 90, "bass")]  # G2 on beat 1 of I
    assert "bass-root" in _rules(lint(bad, ctx, METER))


def test_bass_offbeat_needs_chord_tone_or_license():
    ctx = [HarmonicContext(bar=0, scale=Scale(0, "ionian"), chord_sym="I", chord_pcs=(0, 4, 7))]
    licensed = [NoteEvent(3.0, 1.0, 38, 90, "bass", role="approach")]  # D2 approach
    assert lint(licensed, ctx, METER) == []
    unlicensed = [NoteEvent(3.0, 1.0, 38, 90, "bass")]
    assert "bass-chord-tone" in _rules(lint(unlicensed, ctx, METER))


def test_cadence_realization_checked():
    from musicgen.theory.chords import Chord

    scale = Scale(0, "ionian")
    wrong = [HarmonicContext(bar=0, scale=scale, chord=Chord(4), chord_sym="IV",
                             cadence_slot="cadence", cadence_policy="authentic")]
    assert "cadence" in _rules(lint([], wrong, METER))
    right = [HarmonicContext(bar=0, scale=scale, chord=Chord(1), chord_sym="I",
                             cadence_slot="cadence", cadence_policy="authentic")]
    assert lint([], right, METER) == []


def test_bad_event_values_raise_at_construction():
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 128, 80, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 60, 0, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 0.0, 60, 80, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 60, 80, "kazoo")
