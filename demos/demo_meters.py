"""Compound & triple meters: the same seed and lever arc rendered in 4/4,
3/4 (waltz — snare on beat 2, fifth on the pulse), and 6/8 (compound — two
dotted-quarter pulses, grouped kicks, pickup ghosts, ternary hats). Metric
weights drive melody chord-tone placement and the Accent modifier, so the
whole texture reorients per meter, not just the drums.

Usage: .venv/bin/python demos/demo_meters.py [--seed N] [--no-audio] [--play]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.ir import Meter

ARC = [
    (0,  {"valence": 0.40, "energy": 0.35, "tension": 0.20}),
    (8,  {"valence": 0.30, "energy": 0.60, "tension": 0.40}),
    (16, {"valence": 0.45, "energy": 0.80, "tension": 0.50}),
    (24, {"valence": 0.50, "energy": 0.40, "tension": 0.15}),
]
BARS = 28
METERS = ((Meter(4, 4), "4/4 reference"), (Meter(3, 4), "3/4 waltz"), (Meter(6, 8), "6/8 compound"))


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    for meter, label in METERS:
        engine = MusicEngine(seed=args.seed, config=EngineConfig(meter=meter, mapper=MappingTable()))
        results = run(engine, ARC, BARS)
        strong = ", ".join(str(s) for s in meter.strong_slots())
        print(f"{label:<14} │ {meter.slots} slots, pulses on ({strong})")
        emit(results, meter, f"meter{meter.numerator}{meter.denominator}_s{args.seed}",
             args.out_dir,
             header=f"{label} │ seed {args.seed} │ same levers, different metric hierarchy\n",
             no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
