"""M3 axis demo: a 3x3 grid over (valence, energy) at fixed tension and fixed
seed — each render isolates what the two primary levers do. Per-bar seeding
means differences between cells are the levers' doing, not reshuffled
randomness (PLANS.md §9, §10).

Usage: .venv/bin/python demos/demo_axes.py [--seed N] [--bars 16] [--no-audio]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

VALENCES = (-0.8, 0.0, 0.8)
ENERGIES = (0.15, 0.5, 0.85)
TENSION = 0.35


def tag(x: float) -> str:
    return ("m" if x < 0 else "") + f"{abs(x):.2f}".replace(".", "")


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=16)
    args = parser.parse_args()

    print(f"axes demo │ seed {args.seed} │ tension {TENSION} │ {args.bars} bars per cell\n")
    rows = []
    for valence in VALENCES:
        for energy in ENERGIES:
            engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
            engine.set_affect(valence=valence, energy=energy, tension=TENSION)
            results = [engine.advance_bar() for _ in range(args.bars)]
            stem = f"axes_v{tag(valence)}_e{tag(energy)}"
            emit(results, engine.config.meter, stem, args.out_dir,
                 header=f"{stem} │ valence {valence} energy {energy} tension {TENSION} │ seed {args.seed}\n",
                 no_audio=args.no_audio, quiet=True)
            last = results[-1]
            rows.append((valence, energy, last.context.scale.mode,
                         f"{last.params.tempo_bpm:.0f}", "+".join(last.params.layers),
                         sum(len(r.events) for r in results)))
            print(f"  v {valence:+.1f} e {energy:.2f} │ {rows[-1][2]:<10} │ "
                  f"{rows[-1][3]:>3} BPM │ {rows[-1][5]:>4} events │ {rows[-1][4]}")
    print(f"\n9 renders in {args.out_dir}/axes_*.wav — A/B them per row (valence) and per column (energy)")


if __name__ == "__main__":
    main()
