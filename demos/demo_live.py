"""M5 live demo: the engine playing in real time through FluidSynth, levers on
the keyboard. Generation stays one bar ahead of the playhead; every change
lands with the same boundary quantization as offline automation.

Keys:
  a / z   valence  +/- 0.1        1  explore    (urgent)
  s / x   energy   +/- 0.1        2  threat     (urgent)
  d / c   tension  +/- 0.1        3  combat     (urgent)
  o / l   tempo override +/- 8    4  victory    (urgent)
  k       clear overrides         5  calm       (urgent)
  m / n   modulate a fifth up / down (urgent pivot-chord key change)
  q       quit

Usage: .venv/bin/python demos/demo_live.py [--seed N] [--port NAME]
       [--audio-driver pulseaudio] [--selftest BARS]

--selftest N plays N bars with a scripted sweep and exits (no keyboard) —
use it to verify the live audio chain.
"""

from __future__ import annotations

import argparse
import select
import sys
import termios
import tty

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.live import LivePlayer, find_output_port, open_output, spawn_fluidsynth
from musicgen.theory.scales import TONIC_NAMES

PRESETS = {
    "1": ("explore", {"valence": 0.45, "energy": 0.28, "tension": 0.12}),
    "2": ("threat", {"valence": -0.35, "energy": 0.55, "tension": 0.60}),
    "3": ("combat", {"valence": -0.75, "energy": 0.95, "tension": 0.88}),
    "4": ("victory", {"valence": 0.75, "energy": 0.68, "tension": 0.30}),
    "5": ("calm", {"valence": 0.40, "energy": 0.22, "tension": 0.08}),
}
NUDGE = {"a": ("valence", +0.1), "z": ("valence", -0.1),
         "s": ("energy", +0.1), "x": ("energy", -0.1),
         "d": ("tension", +0.1), "c": ("tension", -0.1)}


def bar_line(result) -> str:
    v, e, t = result.affect
    return (f"▶ bar {result.bar + 1:>3} │ {result.context.scale.name:<13} │ "
            f"{result.context.chord_sym:<10} │ {result.params.tempo_bpm:>6.1f} BPM │ "
            f"val {v:+.2f} en {e:.2f} ten {t:.2f} │ {'+'.join(result.params.layers)}")


def selftest(player: LivePlayer, bars: int) -> None:
    print(f"selftest: {bars} bars with a scripted sweep\n")
    player.max_bars = bars
    player.start()
    acts = list(PRESETS.values())
    applied = -1
    while player._thread.is_alive():
        act = min(player.bars_played // 4, len(acts) - 1)
        if act > applied and player.bars_played < bars:
            applied = act
            name, affect = acts[act % len(acts)]
            print(f"  -> {name}")
            player.set_affect(**affect, urgent=True)
        player._thread.join(timeout=0.1)
    player.stop()
    print(f"\nselftest ok: {player.bars_played} bars played")


def tui(player: LivePlayer, engine: MusicEngine) -> None:
    tempo_override: float | None = None
    key_pc = engine.config.key_tonic  # TUI-side key intent; arrivals confirm in bar lines
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    print(__doc__.split("Usage:")[0])
    player.start()
    try:
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            key = sys.stdin.read(1)
            if key == "q":
                break
            if key in PRESETS:
                name, affect = PRESETS[key]
                player.set_affect(**affect, urgent=True)
                print(f"  preset: {name} {affect}")
            elif key in NUDGE:
                lever, delta = NUDGE[key]
                current = getattr(engine.affect, lever)
                player.set_affect(**{lever: current + delta})
                print(f"  {lever} -> {current + delta:+.2f}")
            elif key in ("o", "l"):
                base = tempo_override if tempo_override is not None else engine.state.current_tempo
                tempo_override = base + (8 if key == "o" else -8)
                player.set_override("tempo_bpm", tempo_override)
                print(f"  tempo override -> {tempo_override:.0f} BPM")
            elif key in ("m", "n"):
                key_pc = (key_pc + (7 if key == "m" else 5)) % 12
                player.request_key(key_pc, urgent=True)
                print(f"  modulating -> {TONIC_NAMES[key_pc]}")
            elif key == "k":
                tempo_override = None
                player.clear_override("tempo_bpm")
                print("  overrides cleared")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        player.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--port", help="MIDI output port name (default: find/spawn FluidSynth)")
    parser.add_argument("--audio-driver", default="pulseaudio")
    parser.add_argument("--selftest", type=int, metavar="BARS")
    args = parser.parse_args()

    fluid_proc = None
    if args.port:
        port = open_output(args.port)
    elif find_output_port("FLUID"):
        port = open_output()
    else:
        print("starting fluidsynth...")
        fluid_proc, port_name = spawn_fluidsynth(audio_driver=args.audio_driver)
        port = open_output(port_name)
    print(f"output: {port.name}")

    engine = MusicEngine(seed=args.seed, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(**PRESETS["1"][1])
    player = LivePlayer(engine, port, on_bar=lambda r: print(bar_line(r)))

    try:
        if args.selftest:
            selftest(player, args.selftest)
        else:
            tui(player, engine)
    finally:
        player.stop()
        port.close()
        if fluid_proc is not None:
            fluid_proc.terminate()
            fluid_proc.wait(timeout=3)


if __name__ == "__main__":
    main()
