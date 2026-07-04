"""M3 tension demo: valence and energy held mid, tension swept 0 -> 1 -> 0
over 48 bars. Listen for: cadence policy shifting authentic -> half ->
deceptive and back, extensions accumulating on chords, phrase-end fills
appearing, dynamics arching (PLANS.md §10).

Usage: .venv/bin/python demos/demo_tension.py [--seed N] [--no-audio]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

CURVE = [
    (0, {"valence": 0.1, "energy": 0.5, "tension": 0.05}),
    (20, {"valence": 0.1, "energy": 0.5, "tension": 0.95}),
    (30, {"valence": 0.1, "energy": 0.5, "tension": 0.90}),
    (48, {"valence": 0.1, "energy": 0.5, "tension": 0.05}),
]
BARS = 48


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    results = run(engine, CURVE, BARS)

    print(f"tension demo │ seed {args.seed} │ {BARS} bars, tension 0 -> 1 -> 0\n")
    for phrase_start in range(0, BARS, engine.config.phrase_bars):
        phrase = results[phrase_start:phrase_start + engine.config.phrase_bars]
        chords = " → ".join(r.context.chord_sym for r in phrase)
        policy = next((r.context.cadence_policy for r in phrase if r.context.cadence_policy), "?")
        tension = phrase[0].affect[2]
        print(f"  ten {tension:.2f} │ cadence {policy:<10} │ {chords}")

    emit(results, engine.config.meter, f"tension_sweep_s{args.seed}", args.out_dir,
         header=f"tension sweep │ seed {args.seed} │ curve {CURVE}\n",
         no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
