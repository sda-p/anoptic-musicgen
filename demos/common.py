"""Shared emission pipeline for demo scripts: lint -> MIDI (+tempo map from
BarResults) -> round-trip check -> annotated dump with lever trajectories ->
decision trace -> optional WAV."""

from __future__ import annotations

from pathlib import Path

from musicgen import audition, midi_io, textdump, verify
from musicgen.ir import Meter


def emit(
    results: list,
    meter: Meter,
    stem: str,
    out_dir: Path,
    *,
    header: str = "",
    no_audio: bool = False,
    gain: float = 0.55,
    play: bool = False,
    quiet: bool = False,
) -> dict[str, Path]:
    events = [ev for r in results for ev in r.events]
    raw = [ev for r in results for ev in r.raw_events]
    contexts = [r.context for r in results]

    verify.assert_clean(raw, contexts, meter, stage="pre")     # grid + melodic rules
    verify.assert_clean(events, contexts, meter, stage="post")  # bounds on what plays

    tempo_points = [p for r in results for p in r.tempo_points]
    if not tempo_points:
        tempo_points = [(0.0, results[0].params.tempo_bpm)]

    mid = midi_io.write_midi(
        out_dir / f"{stem}.mid",
        events,
        tempo_map=tempo_points,
        meter=meter,
        markers=[
            (c.bar * meter.bar_quarters,
             f"bar {c.bar + 1}: {c.chord_sym}" + (f" [{c.cadence_slot}]" if c.cadence_slot else ""))
            for c in contexts
        ],
    )
    problems = midi_io.verify_roundtrip(mid, events)
    if problems:
        raise SystemExit(f"{stem}: MIDI round-trip failed:\n" + "\n".join(problems))

    dump = textdump.dump_bars(
        events, contexts, meter,
        params_by_bar={r.bar: r.params for r in results},
        affect_by_bar={r.bar: r.affect for r in results},
    )
    txt = mid.with_suffix(".txt")
    txt.write_text(header + "\n" + dump + "\n" + textdump.dump_events(events, meter) + "\n")
    trace = mid.with_suffix(".trace.txt")
    trace.write_text("\n".join(line for r in results for line in r.trace) + "\n")

    paths = {"mid": mid, "txt": txt, "trace": trace}
    if not no_audio:
        paths["wav"] = audition.render_wav(mid, gain=gain)
    if not quiet:
        print(f"  {stem}: {len(events)} events, lint clean │ " +
              " │ ".join(str(p) for p in paths.values()))
    if play and "wav" in paths:
        audition.play(paths["wav"])
    return paths


def standard_args(parser):
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--play", action="store_true")
    return parser
