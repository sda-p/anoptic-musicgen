import mido
import pytest

from musicgen.ir import Meter, NoteEvent
from musicgen.midi_io import LAYER_MIDI, PPQ, read_notes, verify_roundtrip, write_midi


@pytest.fixture
def sample_events():
    return [
        # pad chord: three simultaneous notes
        NoteEvent(0.0, 4.0, 60, 80, "pad"),
        NoteEvent(0.0, 4.0, 64, 80, "pad"),
        NoteEvent(0.0, 4.0, 67, 80, "pad"),
        # bass root
        NoteEvent(0.0, 4.0, 36, 88, "bass"),
        # melody 16ths, including a note sustained across the barline
        NoteEvent(2.0, 0.25, 72, 90, "melody"),
        NoteEvent(2.25, 0.25, 74, 70, "melody"),
        NoteEvent(3.5, 1.0, 76, 85, "melody"),  # crosses into bar 2
        # adjacent same-pitch notes: off/on ordering must not cancel them
        NoteEvent(4.5, 0.5, 72, 90, "melody"),
        NoteEvent(5.0, 0.5, 72, 90, "melody"),
        # drums
        NoteEvent(0.0, 0.25, 36, 100, "perc"),
        NoteEvent(1.0, 0.25, 38, 95, "perc"),
    ]


def test_roundtrip(tmp_path, sample_events):
    path = write_midi(tmp_path / "t.mid", sample_events, tempo_map=[(0.0, 96.0)])
    assert verify_roundtrip(path, sample_events) == []


def test_read_notes_fields(tmp_path, sample_events):
    path = write_midi(tmp_path / "t.mid", sample_events)
    notes = read_notes(path)
    assert len(notes) == len(sample_events)
    bass = [n for n in notes if n.channel == LAYER_MIDI["bass"].channel]
    assert len(bass) == 1
    assert bass[0].pitch == 36 and bass[0].velocity == 88
    assert bass[0].start == 0.0 and bass[0].dur == 4.0


def test_adjacent_same_pitch_notes_survive(tmp_path, sample_events):
    path = write_midi(tmp_path / "t.mid", sample_events)
    melody = [n for n in read_notes(path) if n.channel == LAYER_MIDI["melody"].channel]
    starts = sorted(n.start for n in melody if n.pitch == 72)
    assert starts == [2.0, 4.5, 5.0]


def test_file_structure(tmp_path, sample_events):
    path = write_midi(
        tmp_path / "t.mid", sample_events,
        tempo_map=[(0.0, 96.0), (4.0, 120.0)],
        meter=Meter(3, 4),
        markers=[(0.0, "bar 1: I")],
    )
    mid = mido.MidiFile(path)
    assert mid.type == 1 and mid.ticks_per_beat == PPQ

    conductor = mid.tracks[0]
    tempos = [m for m in conductor if m.type == "set_tempo"]
    assert [round(mido.tempo2bpm(m.tempo)) for m in tempos] == [96, 120]
    timesig = next(m for m in conductor if m.type == "time_signature")
    assert (timesig.numerator, timesig.denominator) == (3, 4)
    assert any(m.type == "marker" and m.text == "bar 1: I" for m in conductor)

    track_names = {next(m.name for m in t if m.type == "track_name") for t in mid.tracks}
    assert track_names == {"conductor", "pad", "bass", "melody", "perc"}

    programs = {m.channel: m.program for t in mid.tracks for m in t if m.type == "program_change"}
    assert programs[LAYER_MIDI["pad"].channel] == 89
    assert LAYER_MIDI["perc"].channel not in programs  # drums get no program_change


def test_empty_events_writes_conductor_only(tmp_path):
    path = write_midi(tmp_path / "empty.mid", [])
    mid = mido.MidiFile(path)
    assert len(mid.tracks) == 1
    assert read_notes(path) == []
