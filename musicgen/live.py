"""Live mode: real-time playback with a one-bar look-ahead (PLANS.md M5).

The engine generates bar N+1 while bar N plays — the report's sliding-window
look-ahead in trivial form, since rule-based generation takes microseconds.
A BeatClock maps beats to wall-clock seconds through the piecewise-constant
tempo map; the player thread pops a deadline heap and sends with absolute
monotonic deadlines (no cumulative drift; jitter is sleep granularity).

Lever changes arrive through a queue and are applied at generation time, so
live control has exactly the same boundary-quantization semantics as offline
automation. This is the second module (after midi_io) allowed to import mido.
"""

from __future__ import annotations

import heapq
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import mido

from musicgen.audition import DEFAULT_SF2
from musicgen.clock import BeatClock
from musicgen.midi_io import LAYER_MIDI

__all__ = ["BeatClock", "LivePlayer", "schedule_bar", "setup_programs",
           "find_output_port", "spawn_fluidsynth", "open_output"]


@dataclass(order=True)
class _Entry:
    time: float
    order: int
    seq: int
    kind: str = field(compare=False)      # "midi" | "bar"
    payload: object = field(compare=False)


def schedule_bar(result, clock: BeatClock, seq_start: int = 0, bar_quarters: float = 4.0) -> list[_Entry]:
    """Pure scheduling: one BarResult -> timed entries (tempo points are
    folded into the clock as a side effect, in beat order first)."""
    for beat, bpm in result.tempo_points:
        clock.add_tempo_point(beat, bpm)
    entries: list[_Entry] = []
    seq = seq_start
    entries.append(_Entry(clock.time_at(result.bar * bar_quarters), 2, seq, "bar", result))
    seq += 1
    for ev in result.events:
        spec = LAYER_MIDI[ev.layer]
        on_t = clock.time_at(ev.start)
        off_t = max(clock.time_at(ev.end), on_t + 0.02)
        entries.append(_Entry(on_t, 1, seq, "midi",
                              mido.Message("note_on", channel=spec.channel, note=ev.pitch, velocity=ev.velocity)))
        seq += 1
        entries.append(_Entry(off_t, 0, seq, "midi",
                              mido.Message("note_off", channel=spec.channel, note=ev.pitch, velocity=0)))
        seq += 1
    return entries


class LivePlayer:
    """Runs a MusicEngine against a MIDI output port in real time."""

    def __init__(
        self,
        engine,
        port,
        *,
        lead_seconds: float = 2.5,
        prime_seconds: float = 0.3,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        on_bar: Callable | None = None,
        max_bars: int | None = None,
    ) -> None:
        self.engine = engine
        self.port = port
        self.lead_seconds = lead_seconds
        self.prime_seconds = prime_seconds
        self._clock = clock
        self._sleep = sleep
        self.on_bar = on_bar
        self.max_bars = max_bars
        self._commands: list[tuple] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bars_played = 0

    # --- control (any thread) --------------------------------------------

    def set_affect(self, **kwargs) -> None:
        with self._lock:
            self._commands.append(("affect", kwargs))

    def set_override(self, name: str, value) -> None:
        with self._lock:
            self._commands.append(("override", name, value))

    def clear_override(self, name: str) -> None:
        with self._lock:
            self._commands.append(("clear", name))

    def request_key(self, tonic, *, urgent: bool = False) -> None:
        with self._lock:
            self._commands.append(("key", tonic, urgent))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    # --- playback ----------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="musicgen-live", daemon=True)
        self._thread.start()

    def _apply_pending(self) -> None:
        with self._lock:
            commands, self._commands = self._commands, []
        for command in commands:
            if command[0] == "affect":
                self.engine.set_affect(**command[1])
            elif command[0] == "override":
                self.engine.set_override(command[1], command[2])
            elif command[0] == "clear":
                self.engine.clear_override(command[1])
            elif command[0] == "key":
                self.engine.request_key(command[1], urgent=command[2])

    def run(self) -> None:
        setup_programs(self.port)
        bar_quarters = self.engine.config.meter.bar_quarters
        clock = BeatClock(self._clock() + self.prime_seconds)
        heap: list[_Entry] = []
        seq = 0
        next_bar = 0
        try:
            while not self._stop.is_set():
                now = self._clock()

                while (
                    clock.time_at(next_bar * bar_quarters) < now + self.lead_seconds
                    and (self.max_bars is None or next_bar < self.max_bars)
                    and not self._stop.is_set()
                ):
                    self._apply_pending()
                    result = self.engine.advance_bar()
                    entries = schedule_bar(result, clock, seq, bar_quarters)
                    seq += len(entries)
                    for entry in entries:
                        heapq.heappush(heap, entry)
                    next_bar += 1

                while heap and heap[0].time <= now + 0.001:
                    entry = heapq.heappop(heap)
                    if entry.kind == "midi":
                        self.port.send(entry.payload)
                    elif entry.kind == "bar":
                        self.bars_played += 1
                        if self.on_bar is not None:
                            self.on_bar(entry.payload)

                if self.max_bars is not None and next_bar >= self.max_bars and not heap:
                    break
                wait = min(heap[0].time - self._clock(), 0.02) if heap else 0.02
                if wait > 0:
                    self._sleep(min(wait, 0.02))
        finally:
            self._all_notes_off()

    def _all_notes_off(self) -> None:
        for spec in LAYER_MIDI.values():
            try:
                self.port.send(mido.Message("control_change", channel=spec.channel, control=123, value=0))
                self.port.send(mido.Message("control_change", channel=spec.channel, control=120, value=0))
            except Exception:
                return  # port already closed


# --- port plumbing -----------------------------------------------------------

def setup_programs(port) -> None:
    """Send the per-layer GM programs (a live port has no file header)."""
    for spec in LAYER_MIDI.values():
        if spec.program is not None:
            port.send(mido.Message("program_change", channel=spec.channel, program=spec.program))


def find_output_port(substring: str = "FLUID") -> str | None:
    try:
        names = mido.get_output_names()
    except Exception:
        return None
    return next((n for n in names if substring.lower() in n.lower()), None)


def spawn_fluidsynth(
    sf2: str | Path = DEFAULT_SF2,
    *,
    gain: float = 0.7,
    audio_driver: str = "pulseaudio",
    wait_seconds: float = 5.0,
) -> tuple[subprocess.Popen, str]:
    """Start FluidSynth listening on ALSA sequencer; return (process, port name)."""
    if not Path(sf2).exists():
        raise FileNotFoundError(f"soundfont not found: {sf2}")
    cmd = ["fluidsynth", "-a", audio_driver, "-m", "alsa_seq", "-i",
           "-g", str(gain), "-o", "synth.polyphony=128", str(sf2)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"fluidsynth exited immediately (exit {proc.returncode}); try --audio-driver alsa")
        name = find_output_port("FLUID")
        if name:
            return proc, name
        time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("fluidsynth started but its ALSA port never appeared")


def open_output(port_name: str | None = None, virtual_name: str = "musicgen live"):
    """Open a specific port, else the first FluidSynth port, else a virtual
    port other software can connect to."""
    if port_name:
        return mido.open_output(port_name)
    found = find_output_port("FLUID")
    if found:
        return mido.open_output(found)
    port = mido.open_output(virtual_name, virtual=True)
    print(f"(no FluidSynth port found — opened virtual port {virtual_name!r}; "
          f"connect it with e.g. `aconnect` or start fluidsynth first)")
    return port
