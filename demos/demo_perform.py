"""Wave A A/B demo (REFINEMENT_PLAN.md / PLANS M19): the same piece three ways.

- plain:     the unshaped engine.
- performed: A1 only — deterministic Perform shaping (velocity hairpin,
             contour-tracking loudness, agogic downbeats, luftpause, lay-back)
             plus the cadence micro-ritardando. Pre-modifier IR identical to
             plain: any audible difference IS the performance layer.
- full:      A1 + A2 (perc/arp groove pinned per phrase — pattern identity as
             a contract, fills stay free) + A4 (one planned melodic apex per
             phrase; the hairpin crests with it). These change the notes
             themselves, so raw IR legitimately differs; the groove contract
             is verified with lint_groove.

Usage: .venv/bin/python demos/demo_perform.py [--seed N] [--no-audio]
"""

from __future__ import annotations

import argparse
from statistics import mean

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.melody import MelodyConfig
from musicgen.modifiers import default_chains
from musicgen.verify import lint_groove

AFFECT = {"valence": 0.25, "energy": 0.6, "tension": 0.3}  # tension low: authentic cadences

VARIANTS = (
    ("plain", dict(chains=default_chains())),
    ("performed", dict(chains=default_chains(perform=True), cadence_rit=0.025)),
    ("full", dict(chains=default_chains(perform=True), cadence_rit=0.025,
                  phrase_groove=True, melody=MelodyConfig(plan_apex=True))),
)


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=24)
    args = parser.parse_args()

    print(f"wave A A/B │ seed {args.seed} │ affect {AFFECT}\n")
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
        extra = ""
        if name == "full":
            contract = lint_groove(raw, [r.context for r in results],
                                   {r.bar: r.params for r in results})
            apexes = " ".join(f"{p}:{a.pos + 1}@{a.pitch}"
                              for p, a in sorted(engine.state.apexes.items()))
            extra = (f"\n  {'':<10} groove contract "
                     f"{'CLEAN' if not contract else f'{len(contract)} VIOLATIONS'}"
                     f" │ apex plans (phrase:bar@pitch) {apexes}")
        print(f"  {name:<10} melody velocity by phrase bar │ {curve} │ rits {rits}{extra}")
        emit(results, engine.config.meter, f"perform_{name}_s{args.seed}", args.out_dir,
             header=f"wave A {name} │ seed {args.seed} │ affect {AFFECT}\n",
             no_audio=args.no_audio, quiet=True)

    print(f"\n3 renders in {args.out_dir}/perform_*_s{args.seed}.wav — "
          "plain vs played vs fully shaped")


if __name__ == "__main__":
    main()
