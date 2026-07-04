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


def test_bad_event_values_raise_at_construction():
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 128, 80, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 60, 0, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 0.0, 60, 80, "melody")
    with pytest.raises(ValueError):
        NoteEvent(0.0, 1.0, 60, 80, "kazoo")
