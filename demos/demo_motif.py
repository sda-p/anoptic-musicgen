"""M15 motif lifecycle: render a withhold→release arc where one persistent
signature traverses **introduced** (a fragmentary glimpse, ending on 2̂/7̂) →
**developed** (recurring in disguise, constraint-first) → **completed** (the full,
faithful statement) — and the completed statement lands only on the dramaturg's
payoff spend, so the ear meets the shape whole exactly when the music resolves.

A recognizability score per completed bar confirms the faithful path holds the
motif's identity across the cadential harmony it lands over (where the disguised
constraint-first path bends the shape to each chord). The opening also prints the
primitive check: the same motif realized faithfully vs. constraint-first over a
progression.

Usage: .venv/bin/python demos/demo_motif.py [--seed N] [--no-audio] [--play]
"""
from __future__ import annotations

import argparse
import random

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.melody import MelodyConfig, _nearest_pc_pitch, make_motif
from musicgen.gen.motif import realize_faithful, recognizability
from musicgen.ir import Meter
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale, diatonic_shift, snap_to_scale

ACCRUE, SETTLE = 4, 3
STRONG, LO, HI = {0, 4, 8, 12}, 60, 84


def _constrained(motif, scale, pcs):
    anchor = _nearest_pc_pitch(pcs, (LO + HI) // 2, LO, HI)
    out = []
    for (slot, _), off in zip(motif.rhythm, motif.contour):
        t = diatonic_shift(scale, anchor, off)
        out.append(_nearest_pc_pitch(pcs, t, LO, HI) if slot in STRONG else snap_to_scale(scale, min(max(t, LO), HI)))
    return out


def primitive_check(seed: int) -> None:
    scale = Scale(0, "ionian")
    m = make_motif(random.Random(seed), 0.6, 0.3, MelodyConfig())
    faith, con = [], []
    for deg in (1, 6, 4, 5, 2, 5, 1):
        pcs = Chord(deg).pitch_classes(scale)
        faith.append(recognizability(m, [p for _, _, p in realize_faithful(m, scale, pcs, LO, HI, STRONG)], scale))
        con.append(recognizability(m, _constrained(m, scale, pcs), scale))
    print(f"primitive (contour {m.contour}): faithful {sum(faith)/len(faith):.2f} "
          f"vs constraint-first {sum(con)/len(con):.2f} recognizability over I–vi–IV–V–ii–V–I\n")


def main() -> None:
    args = standard_args(argparse.ArgumentParser(description=__doc__)).parse_args()
    primitive_check(args.seed)

    meter = Meter()
    cfg = EngineConfig(meter=meter, mapper=MappingTable(), dramaturg=DramaturgConfig(leniency=0.5))
    engine = MusicEngine(seed=args.seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    engine.set_affect(valence=-0.4, energy=0.70, tension=0.85)
    for _ in range(ACCRUE * pb):
        results.append(engine.advance_bar())
    engine.set_affect(valence=0.50, energy=0.60, tension=0.08)
    for _ in range(SETTLE * pb):
        results.append(engine.advance_bar())

    lc = engine.state.motif_lifecycle
    print("phrase lifecycle:")
    for r in results:
        if r.bar % pb == 0:
            state = next((t.split("motif ")[1] for t in r.trace if "motif " in t), "?")
            spend = any("SPEND" in t for t in r.trace)
            print(f"  phrase {r.bar // pb}: {state:11s}{'  <- payoff spend' if spend else ''}")

    print(f"\ncompleted phrase {lc.completed_phrase} — the drive into the cadence-fused statement:")
    for r in (r for r in results if r.bar // pb == lc.completed_phrase):
        mel = next((t for t in r.trace if t.startswith("melody:")), "").split("│")[0].strip()
        line = f"  bar {r.bar + 1} over {r.context.chord_sym:6s}: {mel}"
        motif_notes = sorted((e for e in r.raw_events if e.role == "motif"), key=lambda e: e.start)
        if motif_notes:
            recog = recognizability(lc.motif, [e.pitch for e in motif_notes], r.context.scale)
            line += f"  <- faithful statement (recognizability {recog:.2f})"
        print(line)

    emit(results, meter, f"motif_lifecycle_s{args.seed}", args.out_dir,
         header=(f"M15 motif lifecycle │ seed {args.seed} │ introduced→developed→completed; "
                 f"the faithful statement fuses with the spend cadence (phrase {lc.completed_phrase})\n"),
         no_audio=args.no_audio, play=args.play)


if __name__ == "__main__":
    main()
