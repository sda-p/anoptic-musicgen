"""M13 tension-debt ledger (skeleton): the *same* release gesture after 1, 4, and
12 phrases of accrual, so "payoff magnitude scales with accumulated debt" is
audible in one run. While tension stays high the dramaturg **withholds** —
rationing each phrase's cadence to deceptive (it refuses the tonic) — and when
tension drops it **spends** an authentic cadence whose magnitude is monotone in
how long it withheld. A short buildup pays a little; a long one pays big.

Wired into generation (§5.8, M13): cadence rationing (deceptive while withholding,
authentic on the spend); throughout the withholding the walk circles the tonic
(vi/iii instead of landing on I) so the buildup is legible, and a sustained hold
escalates — progressively louder / denser / more accented, a coiled spring not a
plateau; once escalated, gate + register withholding (a top tier held out, the
melody's ambit contracted); and mode-brightening on the spend. All release together
so the texture blooms — the tonic returns, the held tier snaps back, the melody
opens up, the mode brightens, the intensity settles — graded by how long it withheld
(and the magnitude is reported numerically). Still to come (rest of M13): the
structural escalation rungs (ostinato, step-up sequences, partly blocked on M14).

Usage: .venv/bin/python demos/demo_payoff.py [--seed N] [--leniency 0..1] [--no-audio] [--play]
"""
from __future__ import annotations

import argparse

from common import emit, standard_args

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.ir import Meter

ACCRUALS = (1, 4, 12)       # phrases of withholding before the (fixed) release gesture
SETTLE_PHRASES = 2          # release + settle, so each render actually resolves
HIGH = {"valence": -0.2, "energy": 0.70, "tension": 0.85}   # sustained: accrue debt
RELEASE = {"valence": 0.50, "energy": 0.60, "tension": 0.08}  # the same release every time


def scenario(seed: int, accrue_phrases: int, leniency: float):
    meter = Meter()
    cfg = EngineConfig(meter=meter, mapper=MappingTable(),
                       dramaturg=DramaturgConfig(leniency=leniency))
    engine = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    engine.set_affect(**HIGH)
    for _ in range(accrue_phrases * pb):
        results.append(engine.advance_bar())
    led = engine.state.ledger
    withheld = (led.bars_since_authentic, led.deceptions)  # debt just before release
    engine.set_affect(**RELEASE)
    for _ in range(SETTLE_PHRASES * pb):
        results.append(engine.advance_bar())
    return results, meter, withheld, engine.state.ledger.last_spend


def main() -> None:
    parser = standard_args(argparse.ArgumentParser(description=__doc__))
    parser.add_argument("--leniency", type=float, default=0.5,
                        help="0 strict (withholds long) .. 1 lenient (releases readily)")
    args = parser.parse_args()

    rows = []
    for n in ACCRUALS:
        results, meter, (bars, decs), payoff = scenario(args.seed, n, args.leniency)
        rows.append((n, payoff))
        spend = next((ln for r in results for ln in r.trace if "SPEND" in ln), "(no spend)")
        print(f"\n── {n:2d} phrase(s) withheld ─ {bars} bars / {decs} deceptions → payoff {payoff:.3f}")
        print(f"   {spend.strip()}")
        emit(results, meter, f"payoff_accrue{n:02d}_s{args.seed}", args.out_dir,
             header=(f"M13 tension-debt ledger │ seed {args.seed} │ leniency {args.leniency} │ "
                     f"{n} phrases withheld → payoff {payoff:.3f}\n"),
             no_audio=args.no_audio, play=args.play)

    payoffs = [p for _, p in rows]
    monotone = all(a < b for a, b in zip(payoffs, payoffs[1:]))
    print("\npayoff vs accrual:  " + "   ".join(f"{n}→{p:.3f}" for n, p in rows)
          + ("   MONOTONE ✓" if monotone else "   NOT MONOTONE ✗"))
    print("(the M13 acceptance property: payoff magnitude is monotone in accumulated "
          "debt for a fixed release gesture)")
    if not monotone:
        raise SystemExit("payoff magnitude is NOT monotone in accrued debt — M13 regression")


if __name__ == "__main__":
    main()
