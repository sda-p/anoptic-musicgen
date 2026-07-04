"""SMF writing and read-back at the mido boundary (PLANS.md §8.1).

The only module (besides the future live driver, M5) that imports mido;
everything upstream is stdlib-only IR.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import mido

from musicgen.ir import Meter, NoteEvent

PPQ = 480


@dataclass(frozen=True)
class LayerSpec:
    channel: int
    program: int | None  # None -> no program_change (GM drum channel)


LAYER_MIDI = {
    "pad": LayerSpec(channel=0, program=89),    # Pad 2 (warm)
    "bass": LayerSpec(channel=1, program=33),   # Electric Bass (finger)
    "melody": LayerSpec(channel=2, program=11), # Vibraphone
    "arp": LayerSpec(channel=3, program=46),    # Orchestral Harp
    "perc": LayerSpec(channel=9, program=None),
}

_CHANNEL_TO_LAYER = {spec.channel: layer for layer, spec in LAYER_MIDI.items()}


def beats_to_ticks(beats: float) -> int:
    return round(beats * PPQ)


def _to_track(name: str, abs_msgs: list[tuple[int, int, mido.Message]], end_tick: int) -> mido.MidiTrack:
    """Convert (absolute tick, priority, message) triples to a delta-time track.

    Priority orders same-tick messages; note_offs sort before note_ons so
    adjacent same-pitch notes never cancel each other.
    """
    abs_msgs.sort(key=lambda t: (t[0], t[1]))
    track = mido.MidiTrack()
    track.append(mido.MetaMessage("track_name", name=name, time=0))
    prev = 0
    for tick, _, msg in abs_msgs:
        track.append(msg.copy(time=tick - prev))
        prev = tick
    track.append(mido.MetaMessage("end_of_track", time=max(0, end_tick - prev)))
    return track


def write_midi(
    path: str | Path,
    events: Sequence[NoteEvent],
    *,
    tempo_map: Sequence[tuple[float, float]] = ((0.0, 100.0),),  # (beat, bpm)
    meter: Meter = Meter(),
    markers: Sequence[tuple[float, str]] = (),
    end_pad_beats: float = 1.0,
) -> Path:
    """Write events as SMF type 1: a conductor track (time signature, tempo
    map, markers) plus one track per layer present."""
    by_layer: dict[str, list[NoteEvent]] = {}
    for ev in sorted(events, key=lambda e: (e.start, e.pitch)):
        by_layer.setdefault(ev.layer, []).append(ev)
    unknown = set(by_layer) - set(LAYER_MIDI)
    if unknown:
        raise ValueError(f"events reference unmapped layers: {sorted(unknown)}")

    last_tick = max((beats_to_ticks(e.end) for e in events), default=0)
    end_tick = last_tick + beats_to_ticks(end_pad_beats)

    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)

    conductor: list[tuple[int, int, mido.Message]] = [
        (0, 0, mido.MetaMessage("time_signature", numerator=meter.numerator, denominator=meter.denominator)),
    ]
    for beat, bpm in tempo_map:
        conductor.append((beats_to_ticks(beat), 1, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))))
    for beat, text in markers:
        conductor.append((beats_to_ticks(beat), 2, mido.MetaMessage("marker", text=text)))
    mid.tracks.append(_to_track("conductor", conductor, end_tick))

    for layer, spec in LAYER_MIDI.items():
        evs = by_layer.get(layer)
        if not evs:
            continue
        msgs: list[tuple[int, int, mido.Message]] = []
        if spec.program is not None:
            msgs.append((0, 0, mido.Message("program_change", channel=spec.channel, program=spec.program)))
        for ev in evs:
            on, off = beats_to_ticks(ev.start), beats_to_ticks(ev.end)
            if off <= on:
                off = on + 1  # degenerate after rounding; keep it audible
            msgs.append((on, 2, mido.Message("note_on", channel=spec.channel, note=ev.pitch, velocity=ev.velocity)))
            msgs.append((off, 1, mido.Message("note_off", channel=spec.channel, note=ev.pitch, velocity=0)))
        mid.tracks.append(_to_track(layer, msgs, end_tick))

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mid.save(path)
    return path


@dataclass(frozen=True)
class ReadNote:
    start: float  # beats
    dur: float
    pitch: int
    velocity: int
    channel: int


def read_notes(path: str | Path) -> list[ReadNote]:
    """Reconstruct notes from a MIDI file by pairing on/off messages
    (FIFO per channel+pitch). Positions in beats, tempo-independent."""
    mid = mido.MidiFile(path)
    notes: list[ReadNote] = []
    for track in mid.tracks:
        tick = 0
        open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for msg in track:
            tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                open_notes.setdefault((msg.channel, msg.note), []).append((tick, msg.velocity))
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                pending = open_notes.get((msg.channel, msg.note))
                if pending:
                    on_tick, velocity = pending.pop(0)
                    notes.append(ReadNote(
                        start=on_tick / mid.ticks_per_beat,
                        dur=(tick - on_tick) / mid.ticks_per_beat,
                        pitch=msg.note,
                        velocity=velocity,
                        channel=msg.channel,
                    ))
    notes.sort(key=lambda n: (n.start, n.channel, n.pitch))
    return notes


def verify_roundtrip(path: str | Path, events: Sequence[NoteEvent], tol_beats: float = 2.5 / PPQ) -> list[str]:
    """Read the file back and diff it against the IR it was written from.
    Returns a list of problems (empty == clean)."""
    problems: list[str] = []
    got = read_notes(path)
    want = sorted(events, key=lambda e: (e.start, LAYER_MIDI[e.layer].channel, e.pitch))
    if len(got) != len(want):
        problems.append(f"note count: wrote {len(want)}, read back {len(got)}")
    for w, g in zip(want, got):
        if (
            LAYER_MIDI[w.layer].channel != g.channel
            or w.pitch != g.pitch
            or w.velocity != g.velocity
            or abs(w.start - g.start) > tol_beats
            or abs(w.dur - g.dur) > tol_beats
        ):
            problems.append(f"mismatch:\n  wrote {w}\n  read  {g}")
    return problems
