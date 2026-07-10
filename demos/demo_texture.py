"""Wave-C texture demo (REFINEMENT_PLAN C4+C5 / PLANS M24): two renders.

- rotation: every polyphony state enabled with texture as a Tier-2 parameter —
  the piece rotates phrase by phrase through monophonic / homophonic /
  doubled / imitative / counter (never the same state twice running, an
  occasional return to two ago), each phrase's claim verified by
  lint_texture against what actually sounds.
- debt: the dramaturg withholding with the full texture pool at stake —
  buildup phrases are clamped to homophonic (the interesting textures are
  debt currency alongside the arp tier), and the spend releases the richest
  state: the countermelody's entrance IS the payoff gesture.

Usage: .venv/bin/python demos/demo_texture.py [--seed N] [--no-audio]
"""

from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, FormConfig, MusicEngine, TextureConfig
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig
from musicgen.modifiers import default_chains
from musicgen.verify import (
    lint, lint_groove, lint_imitation, lint_outer, lint_periods, lint_texture,
)

TEXTURE = TextureConfig(doubling=True, animate=True, imitation=True,
                        rotate=True, counter=True)


def build(seed: int, dramaturg: DramaturgConfig | None) -> MusicEngine:
    return MusicEngine(seed=seed, config=EngineConfig(
        mapper=MappingTable(), dramaturg=dramaturg,
        chains=default_chains(perform=True), cadence_rit=0.025, phrase_groove=True,
        melody=MelodyConfig(plan_apex=True, counterpoint=True),
        form=FormConfig(cadential_64=True, periods=True,
                        hypermeter=True, bass_inversions=True),
        texture=TEXTURE))


def report(name: str, engine: MusicEngine, results) -> None:
    raw = [e for r in results for e in r.raw_events]
    ctxs = [r.context for r in results]
    pbb = {r.bar: r.params for r in results}
    violations = (lint(raw, ctxs) + lint_outer(raw, ctxs) + lint_periods(raw, ctxs)
                  + lint_groove(raw, ctxs, pbb) + lint_texture(raw, ctxs, pbb)
                  + lint_imitation(raw, ctxs, engine.state.imitation_cells))
    bars = engine.config.phrase_bars
    stats: dict[int, dict[str, int]] = {}
    for e in raw:
        s = stats.setdefault(engine.config.meter.bar_of(e.start) // bars, {})
        key = ("doubling" if e.role == "doubling" else "imitation" if e.role == "imitation"
               else "counter" if e.layer == "counter" else "")
        if key:
            s[key] = s.get(key, 0) + 1
    print(f"  {name}")
    for phrase in sorted(engine.state.phrase_textures):
        tex = engine.state.phrase_textures[phrase]
        s = stats.get(phrase, {})
        extra = " ".join(f"{k}={v}" for k, v in sorted(s.items()))
        print(f"    phrase {phrase}: {tex:<11} {extra}")
    print(f"    all lint families {'CLEAN' if not violations else f'{len(violations)} VIOLATIONS'}")
    for v in violations[:5]:
        print(f"      {v}")


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--bars", type=int, default=48)
    args = parser.parse_args()
    meter = None

    print(f"wave C textures │ seed {args.seed}\n")

    engine = build(args.seed, dramaturg=None)
    engine.set_affect(valence=0.4, energy=0.65, tension=0.35)
    results = [engine.advance_bar() for _ in range(args.bars)]
    meter = engine.config.meter
    report("rotation │ affect (0.4, 0.65, 0.35) static", engine, results)
    emit(results, meter, f"texture_rotation_s{args.seed}", args.out_dir,
         header=f"wave C rotation │ seed {args.seed}\n",
         no_audio=args.no_audio, quiet=True)

    engine = build(args.seed, dramaturg=DramaturgConfig())
    engine.set_affect(valence=0.3, energy=0.6, tension=0.8)
    results = [engine.advance_bar() for _ in range(args.bars // 2)]
    engine.set_affect(tension=0.15)  # cash the ledger
    results += [engine.advance_bar() for _ in range(args.bars // 2)]
    spends = [line for r in results for line in r.trace if "SPEND" in line]
    print()
    report("debt │ tension 0.8 -> 0.15 at the midpoint", engine, results)
    for s in spends:
        print(f"      {s}")
    emit(results, meter, f"texture_debt_s{args.seed}", args.out_dir,
         header=f"wave C texture debt │ seed {args.seed}\n",
         no_audio=args.no_audio, quiet=True)

    print(f"\n2 renders in {args.out_dir}/texture_*_s{args.seed}.wav — "
          "the rotation and the withheld/released countermelody")


if __name__ == "__main__":
    main()
