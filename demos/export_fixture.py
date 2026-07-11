"""IR fixture exporter for the C synth (Anoptic Engine Phase 4 conformance
seam, AUDIO_PLAN §4). Dumps everything an external renderer needs to reproduce
playback exactly: the full tempo map, per-bar affect + the DSP-tier
MusicalParams + effective instruments, and the post-modifier events with tie
flags (unmerged — the consumer runs merge_ties). Flat text, one token-tagged
record per line, fscanf-friendly.

Usage: .venv/bin/python demos/export_fixture.py [--seed N] [--bars N] [--out PATH]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from demo_journey import JOURNEY, BARS

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

LAYER_INDEX = {"pad": 0, "bass": 1, "melody": 2, "counter": 3, "arp": 4, "perc": 5}
TIE_INDEX = {"": 0, "out": 1, "in": 2, "both": 3}
INSTRUMENT_LAYERS = ("pad", "bass", "melody", "arp")  # counter/perc have no tiers


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bars", type=int, default=BARS)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    results = run(engine, JOURNEY, args.bars)
    meter = engine.config.meter

    tempo = [p for r in results for p in r.tempo_points]
    if not tempo:
        tempo = [(0.0, results[0].params.tempo_bpm)]

    out = args.out or Path("out") / f"journey_s{args.seed}.anofix"
    out.parent.mkdir(parents=True, exist_ok=True)

    n_events = sum(len(r.events) for r in results)
    lines: list[str] = []
    lines.append("anosynthfix 1")
    lines.append(f"meter {meter.bar_quarters:.17g}")
    lines.append(f"bars {len(results)}")
    lines.append(f"events {n_events}")
    lines.append(f"tempo {len(tempo)}")
    for beat, bpm in tempo:
        lines.append(f"t {beat:.17g} {bpm:.17g}")
    for r in results:
        v, e, t = r.affect
        p = r.params
        instr = dict(p.instruments)
        names = " ".join(instr.get(layer, "") or "-" for layer in INSTRUMENT_LAYERS)
        lines.append(
            f"bar {r.bar} {v:.17g} {e:.17g} {t:.17g} {p.tempo_bpm:.17g} "
            f"{p.filter_cutoff:.17g} {p.reverb_send:.17g} {p.delay_send:.17g} "
            f"{p.drive:.17g} {p.stereo_width:.17g} {names}"
        )
    for r in results:
        for ev in r.events:
            lines.append(
                f"e {ev.start:.17g} {ev.dur:.17g} {ev.pitch} {ev.velocity} "
                f"{LAYER_INDEX[ev.layer]} {TIE_INDEX[ev.tie]}"
            )
    lines.append("end")

    out.write_text("\n".join(lines) + "\n")
    ties = sum(1 for r in results for ev in r.events if ev.tie)
    print(f"{out}: {len(results)} bars, {len(tempo)} tempo points, "
          f"{n_events} events ({ties} tied halves)")


if __name__ == "__main__":
    main()
