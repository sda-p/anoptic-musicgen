"""Pivot-chord key modulation (PLANS.md §5.7), two renders:

modulation_sN — scripted requests over a lever journey: home -> G (sharpwards
lift), a darker turn, -> Eb (flatwards), then an URGENT snap back home. Watch
the dump: the pivot bar is analyzed in both keys, the new V7 lands on the
pre-cadence slot, and the arrival tonic completes the phrase cadence.

wander_sN — the automatic policy: wander_phrases=2 walks the key ±1 fifth
every two phrases (valence-leaning, springing home past ±2) under static
levers. Same seed, same mapping table — only the key plan differs.

Usage: .venv/bin/python demos/demo_modulation.py [--seed N] [--no-audio] [--play]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

BARS = 48
CUES = {
    0:  ("affect", {"valence": 0.35, "energy": 0.45, "tension": 0.30}),
    10: ("key", "G", False),      # rides phrase 1's cadence: pivot 14, V7 15, arrive 16
    18: ("affect", {"valence": -0.40, "energy": 0.55, "tension": 0.45}),
    26: ("key", "Eb", False),     # flatwards while dark
    34: ("affect", {"valence": -0.20, "energy": 0.75, "tension": 0.70}),
    36: ("key", "C", True),       # crisis snap home, mid-phrase
    41: ("affect", {"valence": 0.50, "energy": 0.45, "tension": 0.15}),
}

WANDER_BARS = 64


def _key_timeline(results) -> list[str]:
    lines, prev = [], None
    for r in results:
        if r.context.modulation:
            lines.append(f"  bar {r.bar + 1:>2}  {r.context.scale.name:<14} {r.context.modulation}")
        elif r.context.scale.name != prev:
            lines.append(f"  bar {r.bar + 1:>2}  {r.context.scale.name}")
        prev = r.context.scale.name
    return lines


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    results = []
    for bar in range(BARS):
        cue = CUES.get(bar)
        if cue and cue[0] == "affect":
            engine.set_affect(**cue[1])
        elif cue:
            engine.request_key(cue[1], urgent=cue[2])
        results.append(engine.advance_bar())

    print(f"modulation demo │ seed {args.seed} │ scripted requests over {BARS} bars")
    print("\n".join(_key_timeline(results)) + "\n")
    emit(results, engine.config.meter, f"modulation_s{args.seed}", args.out_dir,
         header=f"modulation │ seed {args.seed} │ C -> G -> Eb -> urgent C\n",
         no_audio=args.no_audio, play=args.play)

    wanderer = MusicEngine(seed=args.seed, config=EngineConfig(
        mapper=MappingTable(), wander_phrases=2, valence=0.5, energy=0.5, tension=0.35))
    wander_results = [wanderer.advance_bar() for _ in range(WANDER_BARS)]

    print(f"\nwander demo │ wander_phrases=2 │ static levers over {WANDER_BARS} bars")
    print("\n".join(_key_timeline(wander_results)) + "\n")
    emit(wander_results, wanderer.config.meter, f"wander_s{args.seed}", args.out_dir,
         header=f"wander │ seed {args.seed} │ automatic ±1-fifth key walk\n",
         no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
