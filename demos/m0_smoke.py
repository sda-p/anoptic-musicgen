"""M0 smoke demo: hardcoded 4-bar I–IV–V–I in C ionian (block pad chords +
bass roots), rendered to .mid/.txt/.wav with lint and MIDI round-trip checks.

The progression is hand-built on purpose — the harmony engine arrives in M1.
This exercises the full pipeline: IR -> lint -> MIDI -> read-back -> dump -> audio.

Usage: .venv/bin/python demos/m0_smoke.py [--no-audio] [--play] [--out-dir out]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from musicgen import audition, midi_io, textdump, verify
from musicgen.ir import HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.scales import Scale

PROGRESSION = (("I", 1), ("IV", 4), ("V", 5), ("I", 1))  # (roman, root degree)

PAD_OCTAVE = 4
BASS_OCTAVE = 2


def build_bars(scale: Scale, meter: Meter) -> tuple[list[NoteEvent], list[HarmonicContext]]:
    events: list[NoteEvent] = []
    contexts: list[HarmonicContext] = []
    for bar, (sym, root_degree) in enumerate(PROGRESSION):
        start = bar * meter.bar_quarters
        next_sym = PROGRESSION[bar + 1][0] if bar + 1 < len(PROGRESSION) else ""
        triad_degrees = (root_degree, root_degree + 2, root_degree + 4)  # stacked thirds
        contexts.append(HarmonicContext(
            bar=bar,
            scale=scale,
            chord_sym=sym,
            chord_pcs=tuple(scale.pitch_at(d, PAD_OCTAVE) % 12 for d in triad_degrees),
            next_chord_sym=next_sym,
        ))
        for d in triad_degrees:
            pitch = scale.pitch_at(d, PAD_OCTAVE)
            events.append(NoteEvent(start, meter.bar_quarters, pitch, 80, "pad",
                                    degree=scale.degree_of(pitch), chord=sym, role="chord-tone"))
        root = scale.pitch_at(root_degree, BASS_OCTAVE)
        events.append(NoteEvent(start, meter.bar_quarters, root, 88, "bass",
                                degree=scale.degree_of(root), chord=sym, role="root"))
    return events, contexts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--no-audio", action="store_true", help="skip WAV rendering")
    parser.add_argument("--play", action="store_true", help="play the WAV when done")
    args = parser.parse_args()

    meter = Meter(4, 4)
    params = MusicalParams(tempo_bpm=100.0)
    events, contexts = build_bars(Scale(tonic=0, mode="ionian"), meter)

    verify.assert_clean(events, contexts, meter, stage="pre")

    mid = midi_io.write_midi(
        args.out_dir / "m0_smoke.mid",
        events,
        tempo_map=[(0.0, params.tempo_bpm)],
        meter=meter,
        markers=[(c.bar * meter.bar_quarters, f"bar {c.bar + 1}: {c.chord_sym}") for c in contexts],
    )
    problems = midi_io.verify_roundtrip(mid, events)
    if problems:
        raise SystemExit("MIDI round-trip failed:\n" + "\n".join(problems))

    dump = textdump.dump_bars(events, contexts, meter, params)
    txt = mid.with_suffix(".txt")
    txt.write_text(dump + "\n" + textdump.dump_events(events, meter) + "\n")
    print(dump)
    print(f"lint: clean ({len(events)} events) │ round-trip: ok │ {mid} │ {txt}")

    if not args.no_audio:
        wav = audition.render_wav(mid)
        print(f"audio: {wav}")
        if args.play:
            audition.play(wav)


if __name__ == "__main__":
    main()
