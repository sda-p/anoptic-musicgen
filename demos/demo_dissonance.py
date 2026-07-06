"""M14 earned dissonance: dissonance that is itself micro setup/payoff — a
*lintable* structural obligation, not ambient spice. Where the tension-tiered
extensions (§5.2) add colour, an *earned* dissonance plants an obligation and must
discharge it. This demo renders the same withhold→release arc twice — with the
dramaturg's earned dissonance OFF (only ambient colour) and ON — so the difference
reads as intent: over the cadences it controls, the dramaturg ornaments the pad
with **prepared suspensions** that resolve down by step (§5.8). While it withholds
they resolve into deceptive cadences (local relief, the debt stands); on the spend
one resolves into the tonic — the payoff is itself a resolved dissonance.

The M14 acceptance property is checked first, directly on hand-built IR: the
obligation linter passes a proper 4–3 suspension and *fails on a deliberately
unresolved plant*. Then both arcs are emitted (each lints clean at both stages).
Suspensions realized in the pad (increment 2); pedals, cadential appoggiaturas,
and secondary-dominant / modal-mixture obligations follow.

Usage: .venv/bin/python demos/demo_dissonance.py [--seed N] [--leniency 0..1] [--no-audio] [--play]
"""
from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.ir import HarmonicContext, Meter, NoteEvent
from musicgen.theory.scales import Scale
from musicgen.verify import lint

ACCRUE_PHRASES = 4          # sustained high tension: bank debt, ornamenting each cadence
SETTLE_PHRASES = 2          # release + settle: the spend cadence resolves its suspension
HIGH = {"valence": -0.2, "energy": 0.70, "tension": 0.85}
RELEASE = {"valence": 0.50, "energy": 0.60, "tension": 0.08}
_OBLIGATION_RULES = {"suspension", "suspension-prep", "pedal", "borrowed", "tonicize"}


def render(seed: int, earned: bool, leniency: float):
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(),
                       dramaturg=DramaturgConfig(leniency=leniency, earned_dissonance=earned))
    engine = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    engine.set_affect(**HIGH)
    for _ in range(ACCRUE_PHRASES * pb):
        results.append(engine.advance_bar())
    engine.set_affect(**RELEASE)
    for _ in range(SETTLE_PHRASES * pb):
        results.append(engine.advance_bar())
    return results


def acceptance_check() -> None:
    """The M14 property on hand IR: a 4–3 suspension (F prepared over ii, held over
    I, resolving to E) lints clean; drop the resolution and the linter catches it."""
    contexts = [HarmonicContext(bar=0, scale=Scale(0, "ionian"), chord_sym="ii", chord_pcs=(2, 5, 9)),
                HarmonicContext(bar=1, scale=Scale(0, "ionian"), chord_sym="I", chord_pcs=(0, 4, 7))]
    base = [NoteEvent(0.0, 4.0, 65, 74, "pad", role="chord-tone"),   # F prepared over Dm
            NoteEvent(4.0, 4.0, 60, 74, "pad", role="chord-tone"),   # C under
            NoteEvent(4.0, 2.0, 65, 74, "pad", role="suspension")]   # F suspended over C
    for label, extra in (("resolved 4–3", [NoteEvent(6.0, 2.0, 64, 74, "pad", role="resolution")]),
                         ("unresolved plant", [])):
        caught = [v for v in lint(base + extra, contexts, Meter(), stage="pre") if v.rule in _OBLIGATION_RULES]
        print(f"  {label:18s}  " + ("lint clean ✓" if not caught
                                     else "CAUGHT ✗  " + "; ".join(v.message for v in caught)))


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--leniency", type=float, default=0.5)
    args = parser.parse_args()

    print("M14 earned dissonance — acceptance property (obligation linter):")
    acceptance_check()

    print("\nearned-vs-ambient render A/B (same seed, same arc):")
    for earned in (False, True):
        results = render(args.seed, earned, args.leniency)
        susp = sum(1 for r in results for ev in r.raw_events if ev.role == "suspension")
        tag = "earned" if earned else "ambient"
        emit(results, Meter(), f"dissonance_{tag}_s{args.seed}", args.out_dir,
             header=(f"M14 earned dissonance │ seed {args.seed} │ leniency {args.leniency} │ "
                     f"{tag} ({'suspensions deployed' if earned else 'ambient colour only'})\n"),
             no_audio=args.no_audio, play=args.play)
        print(f"    {tag:8s}: {susp} prepared suspension(s) over the dramaturg's cadences")


if __name__ == "__main__":
    main()
