"""M17 authored signature motifs (skeleton): a curated library the generation loop
states when appropriate, so identities recur. This exercises the selection engine
directly — over a chord progression the `MotifDirector` weighs each signature's
ticking overdue×importance pressure against the theory-appropriateness of the
upcoming harmony (its best-fitting transform), and the **leniency** knob trades
recurrence frequency against fit.

The A/B below shows the same library selected strict vs. lenient over one
progression: lenient states the signatures more often; the landmark (high
importance) recurs more than the secondary colour. The render side — stating the
selected signature faithfully (M15), a landmark spending the ledger with cadential
dissonance (M13/M14), and `request_motif` — is wired next (M17.2+).

Usage: .venv/bin/python demos/demo_signatures.py
"""
from __future__ import annotations

import argparse
from collections import Counter

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.motif import motif_fit
from musicgen.gen.signatures import EXAMPLE_LIBRARY, MotifDirector
from musicgen.ir import Meter
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale

SCALE = Scale(0, "ionian")
STRONG, LO, HI = {0, 4, 8, 12}, 60, 84
PROG = (1, 4, 5, 6, 2, 5, 1, 4, 6, 5, 1, 4, 5, 6, 2, 5)
ARC_PHRASES = 8


def run(leniency: float):
    d = MotifDirector(library=EXAMPLE_LIBRARY)
    launches, fits = [], []
    for deg in PROG:
        pcs = Chord(deg).pitch_classes(SCALE)
        sel = d.select(SCALE, pcs, LO, HI, STRONG, leniency, near=72)
        if sel:
            sig, transform, motif_t = sel
            launches.append((sig.tag, transform))
            fits.append(motif_fit(motif_t, SCALE, pcs, LO, HI, STRONG, near=72))
            d.observe(sig.tag, 8)
        else:
            d.age(8)
    return launches, (sum(fits) / len(fits) if fits else 0.0)


def render(seed: int, leniency: float):
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(),
                       dramaturg=DramaturgConfig(leniency=leniency), motif_library=EXAMPLE_LIBRARY)
    engine = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    engine.set_affect(valence=-0.2, energy=0.62, tension=0.55)  # some tension for landmarks to release
    for _ in range(ARC_PHRASES * pb):
        results.append(engine.advance_bar())
    return results


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()

    print("library:", ", ".join(f"{s.tag}(imp {s.importance})" for s in EXAMPLE_LIBRARY))
    print(f"selection over {'-'.join(Chord(d).symbol(SCALE) for d in PROG)}:\n")
    print(f"{'leniency':10s} {'launches':9s} recurrence")
    for leniency in (0.1, 0.3, 0.5, 0.7, 0.9):
        launches, _ = run(leniency)
        counts = Counter(tag for tag, _ in launches)
        bar = "".join("H" if t == "hero" else "t" for t, _ in launches)
        print(f"{leniency:<10.1f} {len(launches):>3}/{len(PROG):<5} {bar}  ({counts['hero']} hero, {counts['threat']} threat)")

    print("\nrender A/B (same seed, same arc — strict vs. lenient):")
    for tag, leniency in (("strict", 0.15), ("lenient", 0.85)):
        results = render(args.seed, leniency)
        pb = 8
        stated = sum(1 for r in results if any("signature '" in t for t in r.trace))
        spends = sum(1 for r in results if any("spends the ledger" in t for t in r.trace))
        emit(results, Meter(), f"signatures_{tag}_s{args.seed}", args.out_dir,
             header=(f"M17 authored signatures │ seed {args.seed} │ {tag} (leniency {leniency}) │ "
                     f"{stated} statements, {spends} landmark arrivals\n"),
             no_audio=args.no_audio, play=args.play)
        print(f"    {tag:8s} (leniency {leniency}): {stated} signature statements, "
              f"{spends} landmark arrivals (hero spends the ledger)")
    print("\n(lenient recurs the signatures more often; a landmark hero statement forces an "
          "authentic\ncadence with cadential dissonance and cashes the tension-debt — an arrival, not just a recurrence.)")


if __name__ == "__main__":
    main()
