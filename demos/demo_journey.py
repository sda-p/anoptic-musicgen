"""M3 flagship demo: a scripted game scenario driven purely through the three
affect levers — explore -> threat -> combat -> victory -> calm — with every
transition happening through the mapper's boundary quantization (no hard
cuts). ~80 bars / roughly three minutes (PLANS.md §10).

Usage: .venv/bin/python demos/demo_journey.py [--seed N] [--no-audio] [--play]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

JOURNEY = [
    (0,  {"valence": 0.45, "energy": 0.28, "tension": 0.12}),  # explore
    (16, {"valence": 0.45, "energy": 0.30, "tension": 0.15}),
    (22, {"valence": -0.20, "energy": 0.45, "tension": 0.50}),  # something's wrong
    (34, {"valence": -0.55, "energy": 0.70, "tension": 0.72}),  # threat closes in
    (40, {"valence": -0.75, "energy": 0.95, "tension": 0.88}),  # combat
    (54, {"valence": -0.70, "energy": 0.92, "tension": 0.85}),
    (58, {"valence": 0.75, "energy": 0.68, "tension": 0.30}),   # victory
    (68, {"valence": 0.55, "energy": 0.40, "tension": 0.15}),
    (80, {"valence": 0.40, "energy": 0.22, "tension": 0.08}),   # calm returns
]
BARS = 80
ACTS = ((0, "explore"), (22, "threat"), (40, "combat"), (58, "victory"), (68, "calm"))


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    results = run(engine, JOURNEY, BARS)

    print(f"journey demo │ seed {args.seed} │ {BARS} bars\n")
    act_of = lambda bar: next(name for start, name in reversed(ACTS) if bar >= start)
    for r in results:
        if r.bar % 8 == 0:
            v, e, t = r.affect
            print(f"  bar {r.bar + 1:>2} [{act_of(r.bar):<7}] {r.context.scale.name:<13} "
                  f"{r.params.tempo_bpm:>6.1f} BPM │ val {v:+.2f} en {e:.2f} ten {t:.2f} │ "
                  f"{'+'.join(r.params.layers)}")

    emit(results, engine.config.meter, f"journey_s{args.seed}", args.out_dir,
         header=f"journey │ seed {args.seed} │ explore->threat->combat->victory->calm\n",
         no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
