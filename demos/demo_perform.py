"""Waves A–C A/B demo (REFINEMENT_PLAN.md / PLANS M19–M23): the same piece three ways.

- plain:     the unshaped engine.
- performed: A1 only — deterministic Perform shaping (velocity hairpin,
             contour-tracking loudness, agogic downbeats, luftpause, lay-back)
             plus the cadence micro-ritardando. Pre-modifier IR identical to
             plain: any audible difference IS the performance layer.
- full:      A1 + A2 (perc/arp groove pinned per phrase — pattern identity as
             a contract, fills stay free) + A3 (outer-voice counterpoint: no
             parallel/direct 5ths & 8ves against the bass, contrary cadence
             approaches) + A4 (one planned melodic apex per phrase; the
             hairpin crests with it) + wave B (cadential 6/4, periods,
             hypermeter, bass planning) + wave C polyphony (melody doubled in
             3rds/6ths when bright, pad figuration instead of static blocks,
             the phrase cell echoed by a second voice). These change the notes
             themselves, so raw IR legitimately differs; the groove/period/
             imitation contracts and the outer-voice frame are verified with
             the lint_* families — and the plain variant's frame violations
             are reported as the A/B.

Usage: .venv/bin/python demos/demo_perform.py [--seed N] [--no-audio]
"""

from __future__ import annotations

import argparse
from statistics import mean

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, FormConfig, MusicEngine, TextureConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.modifiers import default_chains
from musicgen.verify import lint_groove, lint_imitation, lint_outer, lint_periods

AFFECT = {"valence": 0.35, "energy": 0.6, "tension": 0.3}  # bright enough to open the
#                                                            C1 doubling gate

VARIANTS = (
    ("plain", dict(chains=default_chains())),
    ("performed", dict(chains=default_chains(perform=True), cadence_rit=0.025)),
    ("full", dict(chains=default_chains(perform=True), cadence_rit=0.025,
                  phrase_groove=True,
                  melody=MelodyConfig(plan_apex=True, counterpoint=True),
                  form=FormConfig(cadential_64=True, periods=True,
                                  hypermeter=True, bass_inversions=True),
                  texture=TextureConfig(doubling=True, animate=True,
                                        imitation=True, counter=True))),
)


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=24)
    args = parser.parse_args()

    print(f"waves A+B+C A/B │ seed {args.seed} │ affect {AFFECT}\n")
    baseline_raw = None
    for name, cfg in VARIANTS:
        engine = MusicEngine(seed=args.seed,
                             config=EngineConfig(mapper=MappingTable(), **cfg))
        engine.set_affect(**AFFECT)
        results = [engine.advance_bar() for _ in range(args.bars)]

        raw = [e for r in results for e in r.raw_events]
        if baseline_raw is None:
            baseline_raw = raw
        if name == "performed":
            assert raw == baseline_raw, "A1 must not touch the pre-modifier IR"

        bars_q = engine.config.meter.bar_quarters
        melody = [e for r in results for e in r.events if e.layer == "melody"]
        by_pos: dict[int, list[int]] = {}
        for e in melody:
            by_pos.setdefault(int(e.start // bars_q) % engine.config.phrase_bars, []).append(e.velocity)
        curve = " ".join(f"{mean(v):5.1f}" for _, v in sorted(by_pos.items()))
        rits = sum(1 for r in results for line in r.trace if "cadence rit" in line)
        outer = lint_outer(raw, [r.context for r in results])
        extra = ""
        if name == "full":
            ctxs = [r.context for r in results]
            contract = (lint_groove(raw, ctxs, {r.bar: r.params for r in results})
                        + lint_periods(raw, ctxs)
                        + lint_imitation(raw, ctxs, engine.state.imitation_cells))
            apexes = " ".join(f"{p}:{a.pos + 1}@{a.pitch}"
                              for p, a in sorted(engine.state.apexes.items()))
            periods = sum(1 for role in engine.state.planner.periods.values()
                          if role == "antecedent")
            cad64 = sum(1 for c in ctxs if c.obligation == "cadential64")
            inversions = sum(1 for c in ctxs if c.chord and c.chord.inversion == 1)
            doubles = sum(1 for e in raw if e.role == "doubling")
            entries = len(engine.state.imitation_cells)
            animated = sum(1 for r in results for line in r.trace if "animate:" in line)
            counters = sum(1 for e in raw if e.layer == "counter")
            extra = (f"\n  {'':<10} groove+period+imitation contracts "
                     f"{'CLEAN' if not contract else f'{len(contract)} VIOLATIONS'}"
                     f" │ periods {periods} │ cadential 6/4s {cad64}"
                     f" │ bass inversions {inversions}"
                     f"\n  {'':<10} doubles {doubles} │ imitation entries {entries}"
                     f" │ animated pad bars {animated} │ counter notes {counters}"
                     f"\n  {'':<10} apex plans (phrase:bar@pitch) {apexes}")
        print(f"  {name:<10} melody velocity by phrase bar │ {curve} │ rits {rits} "
              f"│ outer-voice violations {len(outer)}{extra}")
        emit(results, engine.config.meter, f"perform_{name}_s{args.seed}", args.out_dir,
             header=f"wave A {name} │ seed {args.seed} │ affect {AFFECT}\n",
             no_audio=args.no_audio, quiet=True)

    print(f"\n3 renders in {args.out_dir}/perform_*_s{args.seed}.wav — "
          "plain vs played vs fully shaped")


if __name__ == "__main__":
    main()
