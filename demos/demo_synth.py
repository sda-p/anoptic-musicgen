"""M6 demo: the journey scenario rendered through the signalflow synthesis
backend — subtractive/FM voices, lever-driven filter and send automation,
tempo-synced delay, hand-rolled Schroeder reverb, kick-triggered ducking.

Renders offline (sample-accurate, faster than realtime) to out/journey_synth.wav.
A/B against the GM render: demos/demo_journey.py -> out/journey_s42.wav.

Usage: .venv/bin/python demos/demo_synth.py [--seed N] [--bars N] [--live]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from demo_journey import JOURNEY, ACTS

from musicgen.control.automation import run
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.synth.render import RealtimeSynthPlayer, render_offline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--bars", type=int, default=80)
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    parser.add_argument("--live", action="store_true", help="play in real time instead of rendering")
    args = parser.parse_args()

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))

    if args.live:
        player = RealtimeSynthPlayer(
            engine, max_bars=args.bars,
            on_bar=lambda r: print(
                f"▶ bar {r.bar + 1:>3} │ {r.context.scale.name:<13} │ {r.context.chord_sym:<10} │ "
                f"{r.params.tempo_bpm:>6.1f} BPM │ cut {r.params.filter_cutoff / 1000:.1f}k "
                f"rev {r.params.reverb_send:.2f} drv {r.params.drive:.2f}"),
        )
        from musicgen.control.automation import affect_at
        player.start()
        while player._thread.is_alive():
            player.set_affect(**affect_at(JOURNEY, min(player.bars_played, args.bars)))
            player._thread.join(timeout=0.2)
        player.stop()
        return

    results = run(engine, JOURNEY, args.bars)
    act_of = lambda bar: next(name for start, name in reversed(ACTS) if bar >= start)
    for r in results:
        if r.bar % 8 == 0:
            print(f"  bar {r.bar + 1:>2} [{act_of(r.bar):<7}] {r.context.scale.name:<13} "
                  f"{r.params.tempo_bpm:>6.1f} BPM │ cut {r.params.filter_cutoff / 1000:4.1f}k "
                  f"rev {r.params.reverb_send:.2f} dly {r.params.delay_send:.2f} "
                  f"drv {r.params.drive:.2f} wid {r.params.stereo_width:.2f}")
    path = render_offline(results, engine.config.meter, args.out_dir / f"journey_synth_s{args.seed}.wav")
    print(f"\nsynth render: {path}")
    print(f"A/B GM render: out/journey_s{args.seed}.wav (demos/demo_journey.py)")


if __name__ == "__main__":
    main()
