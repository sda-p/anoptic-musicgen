"""M11 voice-engine showcase (synth backend only): the pad pinned to the
MORPHING WAVETABLE patch (crossfade scans dark->bright over each note), the
melody to the SAMPLED BELL (a synthesized 'recording' repitched from C5 —
higher notes ring shorter, the honest resampling artifact), while a tension
arc blooms the GRANULAR SHIMMER (octave-up grains from the pad's own recent
past, sprayed into the reverb) and big energy rises trigger bar-long filter
SWEEPS. The mod matrix breathes underneath throughout.

Usage: .venv/bin/python demos/demo_voices.py [--seed N] [--play]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from musicgen import audition, verify
from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.synth.render import render_offline

ARC = [
    (0,  {"valence": 0.35, "energy": 0.25, "tension": 0.15}),
    (8,  {"valence": 0.20, "energy": 0.45, "tension": 0.55}),
    (14, {"valence": -0.10, "energy": 0.85, "tension": 0.90}),  # shimmer + sweep territory
    (22, {"valence": 0.45, "energy": 0.35, "tension": 0.20}),
]
BARS = 28


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    engine.set_override("instruments", (
        ("pad", "morph"), ("bass", "round"), ("melody", "keys"), ("arp", "pluck")))
    results = run(engine, ARC, BARS)

    contexts = [r.context for r in results]
    verify.assert_clean([e for r in results for e in r.raw_events], contexts,
                        engine.config.meter, stage="pre")
    verify.assert_clean([e for r in results for e in r.events], contexts,
                        engine.config.meter, stage="post")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = render_offline(results, engine.config.meter,
                          args.out_dir / f"voices_s{args.seed}.wav")
    print(f"voices demo │ seed {args.seed} │ {BARS} bars, lint clean │ {path}")
    print("listen for: wavetable pads opening per note │ bell melody ringing shorter "
          "up high │ granular shimmer blooming with tension (bars 15-22) │ the filter "
          "sweep on the energy jump")
    if args.play:
        audition.play(path)


if __name__ == "__main__":
    main()
