"""Drivers for the synthesis console.

render_offline: sample-accurate non-realtime render of BarResults straight to
a WAV file — the graph is stepped in exact chunks between scheduled moments
(note-ons, per-bar parameter retargets, voice removals), which is precisely
the block-scheduling contract the engine's C library will need.

RealtimeSynthPlayer: the live equivalent — same one-bar look-ahead pattern as
live.LivePlayer, but triggering console voices directly instead of MIDI.
"""

from __future__ import annotations

import heapq
import threading
import time
from pathlib import Path
from typing import Callable

from musicgen.clock import BeatClock
from musicgen.ir import Meter
from musicgen.synth.console import Console, ConsoleConfig

_KIND_PARAMS, _KIND_NOTE, _KIND_REMOVE = 0, 1, 2


def _drain_until(graph, console, target_frame: int, pos: int, active: list, block: int) -> int:
    """Render up to target_frame, detaching finished voices at their exact
    frames along the way. Returns the new position."""
    while pos < target_frame:
        stop = min(target_frame, active[0][0] if active else target_frame)
        while pos < stop:
            step = min(block, stop - pos)
            graph.render(step)
            pos += step
        while active and active[0][0] <= pos:
            _, layer, node = heapq.heappop(active)
            console.remove(layer, node)
    return pos


def render_offline(
    results: list,
    meter: Meter,
    path: str | Path,
    *,
    sample_rate: int = 44100,
    tail_seconds: float = 2.5,
    block: int = 1024,
    config: ConsoleConfig | None = None,
) -> Path:
    """Note: signalflow may print "Warning: buffer overrun?" during dense
    passages — that is its realtime CPU>100% check firing while we render
    faster than realtime. Harmless here (see SYNTHESIS.md, findings)."""
    import signalflow as sf

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = sf.AudioGraph(
        output_device=sf.AudioOut_Dummy(num_channels=2, sample_rate=sample_rate,
                                        buffer_size=max(block, 1024)),
        start=False,
    )
    try:
        console = Console(graph, config or ConsoleConfig())
        clock = BeatClock(0.0)

        schedule: list[tuple[int, int, object]] = []
        last_note_end = 0
        for r in results:
            for beat, bpm in r.tempo_points:
                clock.add_tempo_point(beat, bpm)
            bar_frame = int(clock.time_at(r.bar * meter.bar_quarters) * sample_rate)
            schedule.append((bar_frame, _KIND_PARAMS, r))
            for ev in r.events:
                on = clock.time_at(ev.start)
                schedule.append((int(on * sample_rate), _KIND_NOTE,
                                 (ev, clock.time_at(ev.end) - on)))
                last_note_end = max(last_note_end, int(clock.time_at(ev.end) * sample_rate))
        schedule.sort(key=lambda item: (item[0], item[1]))

        # Synchronous capture: record the master into a preallocated buffer
        # (the async file recorder overruns when stepped faster than realtime).
        total_frames = last_note_end + int(tail_seconds * sample_rate)
        capture = sf.Buffer(2, total_frames)
        recorder = sf.BufferRecorder(capture, console.master)
        graph.add_node(recorder)

        pos = 0
        active: list[tuple[int, str, object]] = []  # (end_frame, layer, node) heap
        for frame, kind, payload in schedule:
            pos = _drain_until(graph, console, frame, pos, active, block)
            if kind == _KIND_PARAMS:
                console.apply_params(payload.params, payload.affect, payload.params.tempo_bpm)
            else:
                ev, dur_seconds = payload
                layer, node, total = console.note_on(ev, dur_seconds)
                heapq.heappush(active, (pos + int(total * sample_rate), layer, node))

        _drain_until(graph, console, total_frames, pos, active, block)
        capture.save(str(path))
    finally:
        graph.destroy()
    return path


class RealtimeSynthPlayer:
    """Real-time twin of live.LivePlayer, driving the console directly."""

    def __init__(
        self,
        engine,
        *,
        config: ConsoleConfig | None = None,
        lead_seconds: float = 2.5,
        prime_seconds: float = 0.3,
        on_bar: Callable | None = None,
        max_bars: int | None = None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.lead_seconds = lead_seconds
        self.prime_seconds = prime_seconds
        self.on_bar = on_bar
        self.max_bars = max_bars
        self._commands: list[tuple] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bars_played = 0

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

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="musicgen-synth", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

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
        import signalflow as sf

        graph = sf.AudioGraph(start=True)  # system audio output
        try:
            console = Console(graph, self.config or ConsoleConfig())
            bar_quarters = self.engine.config.meter.bar_quarters
            clock = BeatClock(time.monotonic() + self.prime_seconds)
            heap: list[tuple[float, int, int, object]] = []  # (time, kind, seq, payload)
            seq = 0
            next_bar = 0
            while not self._stop.is_set():
                now = time.monotonic()
                while (
                    clock.time_at(next_bar * bar_quarters) < now + self.lead_seconds
                    and (self.max_bars is None or next_bar < self.max_bars)
                    and not self._stop.is_set()
                ):
                    self._apply_pending()
                    result = self.engine.advance_bar()
                    for beat, bpm in result.tempo_points:
                        clock.add_tempo_point(beat, bpm)
                    heapq.heappush(heap, (clock.time_at(next_bar * bar_quarters), _KIND_PARAMS, seq, result))
                    seq += 1
                    for ev in result.events:
                        on = clock.time_at(ev.start)
                        heapq.heappush(heap, (on, _KIND_NOTE, seq, (ev, clock.time_at(ev.end) - on)))
                        seq += 1
                    next_bar += 1

                while heap and heap[0][0] <= now + 0.002:
                    _, kind, _, payload = heapq.heappop(heap)
                    if kind == _KIND_PARAMS:
                        console.apply_params(payload.params, payload.affect, payload.params.tempo_bpm)
                        self.bars_played += 1
                        if self.on_bar is not None:
                            self.on_bar(payload)
                    elif kind == _KIND_NOTE:
                        ev, dur_seconds = payload
                        layer, node, total = console.note_on(ev, dur_seconds)
                        heapq.heappush(heap, (time.monotonic() + total, _KIND_REMOVE, seq, (layer, node)))
                        seq += 1
                    else:
                        console.remove(*payload)

                if self.max_bars is not None and next_bar >= self.max_bars and not heap:
                    break
                wait = min(heap[0][0] - time.monotonic(), 0.02) if heap else 0.02
                if wait > 0:
                    time.sleep(min(wait, 0.02))
        finally:
            graph.destroy()
