"""Energy-driven instrument swaps (vertical re-orchestration): an energy
staircase climbs through the mapping table's patch tiers — pad warm->bright,
bass round->driven, melody soft->hard, arp pluck->glass — then falls back
down, with hysteresis holding patches near their thresholds. Swaps are
phrase-quantized (urgent affect demotes to the barline) and land as GM
program changes in the .mid; the synth backend picks voice variants from the
same params. Notes are identical either way — only timbre moves.

Usage: .venv/bin/python demos/demo_instruments.py [--seed N] [--no-audio] [--play]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

STAIRCASE = [  # (bar, energy) — urgent on the spike so the swap is audible mid-phrase
    (0, 0.15, False), (8, 0.48, False), (16, 0.70, False),
    (22, 0.95, True), (32, 0.58, False), (40, 0.15, False),
]
BARS = 48


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(
        mapper=MappingTable(), phrase_bars=8, valence=0.25, tension=0.35))
    cues = {bar: (energy, urgent) for bar, energy, urgent in STAIRCASE}
    results = []
    for bar in range(BARS):
        if bar in cues:
            energy, urgent = cues[bar]
            engine.set_affect(energy=energy, urgent=urgent)
        results.append(engine.advance_bar())

    print(f"instrument-swap demo │ seed {args.seed} │ energy staircase over {BARS} bars\n")
    for r in results:
        for line in r.trace:
            if line.startswith("instruments:"):
                _, _, rest = line.partition(" ")
                print(f"  bar {r.bar + 1:>2}  {rest}")
    print()
    emit(results, engine.config.meter, f"instruments_s{args.seed}", args.out_dir,
         header=f"instrument swaps │ seed {args.seed} │ energy staircase\n",
         no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
