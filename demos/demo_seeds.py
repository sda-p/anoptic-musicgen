"""M3 variety demo: identical levers, five seeds — the "varied" requirement.
Same affect, same mapping, different musical surface (PLANS.md §10).

Usage: .venv/bin/python demos/demo_seeds.py [--bars 16] [--no-audio]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

AFFECT = {"valence": 0.2, "energy": 0.55, "tension": 0.4}


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=16)
    args = parser.parse_args()

    print(f"seeds demo │ affect {AFFECT} │ {args.bars} bars per seed\n")
    for seed in (1, 2, 3, 4, 5):
        engine = MusicEngine(seed=seed, config=EngineConfig(mapper=MappingTable()))
        engine.set_affect(**AFFECT)
        results = [engine.advance_bar() for _ in range(args.bars)]
        chords = " → ".join(r.context.chord_sym for r in results[:8])
        print(f"  seed {seed}: {chords}")
        emit(results, engine.config.meter, f"seeds_s{seed}", args.out_dir,
             no_audio=args.no_audio, quiet=True)
    print(f"\n5 renders in {args.out_dir}/seeds_s*.wav")


if __name__ == "__main__":
    main()
