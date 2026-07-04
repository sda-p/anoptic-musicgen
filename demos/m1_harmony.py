"""M1 demo: the harmony backbone — 32 bars of functional progression walk with
cadence slots (cycling authentic / half / deceptive / authentic per phrase),
voice-led pad, and bass with approach tones. Static mid levers per PLANS.md M1.

Usage: .venv/bin/python demos/m1_harmony.py [--seed N] [--bars N] [--tonic C]
       [--mode ionian] [--tension 0.45] [--valence 0.3] [--no-audio] [--play]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from musicgen import audition, midi_io, textdump, verify
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import MusicalParams
from musicgen.theory.pitch import name_to_midi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bars", type=int, default=32)
    parser.add_argument("--tonic", default="C")
    parser.add_argument("--mode", default="ionian")
    parser.add_argument("--tension", type=float, default=0.45)
    parser.add_argument("--valence", type=float, default=0.3)
    parser.add_argument("--tempo", type=float, default=88.0)
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    config = EngineConfig(
        params=MusicalParams(tempo_bpm=args.tempo, note_density=0.5, layers=("pad", "bass")),
        key_tonic=name_to_midi(f"{args.tonic}4") % 12,
        mode=args.mode,
        tension=args.tension,
        valence=args.valence,
    )
    engine = MusicEngine(seed=args.seed, config=config)

    results = [engine.advance_bar() for _ in range(args.bars)]
    events = [ev for r in results for ev in r.events]
    contexts = [r.context for r in results]

    verify.assert_clean(events, contexts, config.meter, stage="pre")

    stem = f"m1_harmony_s{args.seed}"
    mid = midi_io.write_midi(
        args.out_dir / f"{stem}.mid",
        events,
        tempo_map=[(0.0, config.params.tempo_bpm)],
        meter=config.meter,
        markers=[
            (c.bar * config.meter.bar_quarters,
             f"bar {c.bar + 1}: {c.chord_sym}" + (f" [{c.cadence_slot}]" if c.cadence_slot else ""))
            for c in contexts
        ],
    )
    problems = midi_io.verify_roundtrip(mid, events)
    if problems:
        raise SystemExit("MIDI round-trip failed:\n" + "\n".join(problems))

    header = (
        f"m1_harmony │ seed {args.seed} │ {contexts[0].scale.name} │ {args.bars} bars │ "
        f"tension {args.tension} valence {args.valence} │ {config.params.tempo_bpm:g} BPM\n"
    )
    dump = textdump.dump_bars(events, contexts, config.meter, config.params)
    txt = mid.with_suffix(".txt")
    txt.write_text(header + "\n" + dump + "\n" + textdump.dump_events(events, config.meter) + "\n")
    trace_path = mid.with_suffix(".trace.txt")
    trace_path.write_text("\n".join(line for r in results for line in r.trace) + "\n")

    progression = [c.chord_sym for c in contexts]
    print(header)
    for phrase_start in range(0, len(progression), config.phrase_bars):
        print("  " + " → ".join(progression[phrase_start:phrase_start + config.phrase_bars]))
    print(f"\nchord usage: {dict(Counter(progression).most_common())}")
    print(f"lint: clean ({len(events)} events) │ round-trip: ok")
    print(f"files: {mid} │ {txt} │ {trace_path}")

    if not args.no_audio:
        wav = audition.render_wav(mid)
        print(f"audio: {wav}")
        if args.play:
            audition.play(wav)


if __name__ == "__main__":
    main()
