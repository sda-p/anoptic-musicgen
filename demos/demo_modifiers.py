"""M4 A/B demo: the same 16 bars rendered three ways — dry (no modifiers),
default chains (strum, humanize, articulate, accent, echo), and a wet variant
(heavy swing, deep echo, wide strum). Pre-modifier IR is identical across all
three (per-bar seeding), so any audible difference IS the modifiers.

Usage: .venv/bin/python demos/demo_modifiers.py [--seed N] [--no-audio]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.modifiers import Accent, Articulate, Echo, Humanize, Strum, Swing, default_chains

AFFECT = {"valence": 0.25, "energy": 0.65, "tension": 0.4}

WET_CHAINS = {
    "pad": (Strum(spread=0.12), Humanize(t_sigma=0.02, v_sigma=6.0)),
    "bass": (Humanize(t_sigma=0.01, v_sigma=4.0),),
    "melody": (Articulate(), Accent(), Swing(amount=0.8), Humanize(t_sigma=0.02, v_sigma=8.0)),
    "arp": (Swing(amount=0.8), Echo(delay=0.5, decay=0.65, repeats=3)),
    "perc": (Swing(amount=0.8), Humanize(t_sigma=0.008, v_sigma=5.0)),
}

VARIANTS = (("dry", {}), ("default", default_chains()), ("wet", WET_CHAINS))


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=16)
    args = parser.parse_args()

    print(f"modifiers A/B │ seed {args.seed} │ affect {AFFECT}\n")
    baseline_raw = None
    for name, chains in VARIANTS:
        engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable(), chains=chains))
        engine.set_affect(**AFFECT)
        results = [engine.advance_bar() for _ in range(args.bars)]

        raw = [e for r in results for e in r.raw_events]
        final = [e for r in results for e in r.events]
        if baseline_raw is None:
            baseline_raw = raw
        assert raw == baseline_raw, "pre-modifier IR must be identical across variants"

        off_grid = sum(1 for e in final if (e.start / 0.25) % 1 > 1e-9)
        print(f"  {name:<8} {len(final):>4} events │ {off_grid:>4} moved off-grid │ "
              f"echoes {sum(1 for e in final if e.role == 'echo'):>3}")
        emit(results, engine.config.meter, f"modifiers_{name}_s{args.seed}", args.out_dir,
             header=f"modifiers {name} │ seed {args.seed} │ affect {AFFECT}\n",
             no_audio=args.no_audio, quiet=True)

    print(f"\n3 renders in {args.out_dir}/modifiers_*_s{args.seed}.wav — identical notes, different feel")


if __name__ == "__main__":
    main()
