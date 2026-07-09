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
from pathlib import Path
from typing import Callable

from musicgen.clock import BeatClock
from musicgen.control.automation import affect_at
from musicgen.ir import Meter
from musicgen.synth.console import Console, ConsoleConfig

_KIND_PARAMS, _KIND_NOTE, _KIND_REMOVE = 0, 1, 2


def _drain_until(graph, console, target_frame: int, pos: int, active: list, block: int) -> int:
    """Render up to target_frame, detaching finished voices at their exact
    frames along the way. Returns the new position.

    Heap entries are (end_frame, seq, layer, node): the seq tiebreaker is
    load-bearing — same-frame voices are common (chords), and comparing
    signalflow node objects CONSTRUCTS comparison nodes inside the live
    graph (operator overloading), which then die at GC-determined moments
    mid-render. See SYNTHESIS.md finding 8."""
    while pos < target_frame:
        stop = min(target_frame, active[0][0] if active else target_frame)
        while pos < stop:
            step = min(block, stop - pos)
            graph.render(step)
            pos += step
        while active and active[0][0] <= pos:
            _, _, layer, node = heapq.heappop(active)
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
    dither: bool = True,
) -> Path:
    """dither adds deterministic TPDF noise at 1 LSB of 16-bit before the
    final quantization (and only there — never while the signal stays float).

    Note: signalflow may print "Warning: buffer overrun?" during dense
    passages — that is its realtime CPU>100% check firing while we render
    faster than realtime. Harmless here (see SYNTHESIS.md, findings)."""
    import numpy as np
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
        seq = 0
        active: list[tuple[int, int, str, object]] = []  # (end_frame, seq, layer, node) heap
        for frame, kind, payload in schedule:
            pos = _drain_until(graph, console, frame, pos, active, block)
            if kind == _KIND_PARAMS:
                console.apply_params(payload.params, payload.affect, payload.params.tempo_bpm,
                                     bar_seconds=meter.bar_quarters * 60.0 / payload.params.tempo_bpm)
            else:
                ev, dur_seconds = payload
                layer, node, total = console.note_on(ev, dur_seconds)
                heapq.heappush(active, (pos + int(total * sample_rate), seq, layer, node))
                seq += 1

        _drain_until(graph, console, total_frames, pos, active, block)
        if dither:
            # TPDF at +-1 LSB, seeded: renders stay bit-reproducible
            rng = np.random.default_rng(0x0D17)
            shape = np.asarray(capture.data).shape
            noise = (rng.random(shape) - rng.random(shape)) * (1.0 / 32768.0)
            capture.data[:] = np.asarray(capture.data) + noise.astype(np.float32)
        capture.save(str(path))
    finally:
        graph.destroy()
    return path


class RealtimeSynthPlayer:
    """Real-time twin of live.LivePlayer, driving the console directly.

    Renders single-threaded: this player owns the render loop and pushes blocks
    to the device itself (sounddevice), rather than letting signalflow spawn an
    audio thread. That is deliberate — the console graph is mutated constantly
    (voice attach/detach, sweep/duck envelopes), and mutating a live graph from
    a second thread while signalflow's audio thread renders it races on node
    refcounts and bus input vectors, and segfaults. One thread, render and
    mutation interleaved, is exactly the (crash-free) offline contract.
    See SYNTHESIS.md finding 9."""

    def __init__(
        self,
        engine,
        *,
        config: ConsoleConfig | None = None,
        lead_seconds: float = 2.5,
        on_bar: Callable | None = None,
        max_bars: int | None = None,
        start_bar: int = 0,
        automation=None,
    ) -> None:
        self.engine = engine
        self.config = config
        self.lead_seconds = lead_seconds
        self.on_bar = on_bar
        self.max_bars = max_bars
        self.start_bar = int(start_bar)  # jump-to-bar: warm the engine here before playing
        self._automation = automation    # None, or (curve, loop_bars): affect driven per bar
        self._commands: list[tuple] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.bars_played = 0
        self.console = None  # set once run() builds it; None while stopped
        self._pending_config = None  # a ConsoleConfig to rebuild into (structural change)
        self._last_result = None  # last applied bar, re-applied after a rebuild

    def set_affect(self, **kwargs) -> None:
        with self._lock:
            self._commands.append(("affect", kwargs))

    def set_override(self, name: str, value) -> None:
        with self._lock:
            self._commands.append(("override", name, value))

    def clear_override(self, name: str) -> None:
        with self._lock:
            self._commands.append(("clear", name))

    def set_mapping(self, table) -> None:
        """Hot-swap the whole (frozen) MappingTable; applied at the next bar
        edge. The engine re-reads config.mapper each bar, so the swap is atomic
        and deterministic — the M12 live-heuristics path."""
        with self._lock:
            self._commands.append(("mapping", table))

    def set_console(self, config) -> None:
        """Swap the ConsoleConfig — a STRUCTURAL change (EQ, FDN, mod-matrix,
        limiter…). Unlike the mapped DSP params (live via Smooth controls), this
        rebuilds the console graph, so it lands with a brief gap. See the
        live-vs-rebuild split in SYNTHESIS.md finding 9."""
        with self._lock:
            self._commands.append(("console", config))

    def set_automation(self, curve, loop_bars: int) -> None:
        """Drive affect from a breakpoint curve every bar; curve=None disables
        (manual affect resumes). Evaluated on the generation thread keyed by the
        engine's own bar, so it survives a seek and loops cleanly. This is the
        live twin of control.automation — the demo ARCs made drawable."""
        with self._lock:
            self._commands.append(("automation", curve, loop_bars))

    def set_dramaturg(self, cfg) -> None:
        """Hot-swap the dramaturg's (frozen) config between bars — leniency and
        the other knobs plus the enable toggle. The ledger state is preserved (it
        lives on the engine's ConductorState, not the config)."""
        with self._lock:
            self._commands.append(("dramaturg", cfg))

    def set_perform(self, fields: dict) -> None:
        """Hot-swap the performed-surface knobs (REFINEMENT_PLAN wave A) between
        bars: {shaping, cadence_rit, phrase_groove, plan_apex}. All are read
        per-bar by the conductor, so the swap is atomic; the per-phrase caches
        (grooves, apexes) persist across toggles."""
        with self._lock:
            self._commands.append(("perform", dict(fields)))

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
            elif command[0] == "mapping":
                self.engine.config.mapper = command[1]
            elif command[0] == "console":
                self._pending_config = command[1]
            elif command[0] == "automation":
                self._automation = (command[1], command[2]) if command[1] else None
            elif command[0] == "dramaturg":
                if self.engine.dramaturg is not None:
                    self.engine.dramaturg.cfg = command[1]  # swap knobs, keep the ledger
                else:
                    from musicgen.gen.dramaturg import Dramaturg
                    self.engine.dramaturg = Dramaturg(command[1])
            elif command[0] == "perform":
                from dataclasses import replace as _replace
                from musicgen.gen.conductor import FormConfig
                from musicgen.modifiers import default_chains
                f, cfg = command[1], self.engine.config
                cfg.chains = default_chains(perform=bool(f["shaping"]))
                cfg.cadence_rit = float(f["cadence_rit"]) if f["shaping"] else 0.0
                cfg.phrase_groove = bool(f["phrase_groove"])
                cfg.melody = _replace(cfg.melody, plan_apex=bool(f["plan_apex"]),
                                      counterpoint=bool(f["counterpoint"]))
                cfg.form = FormConfig(cadential_64=bool(f["cadential_64"]),
                                      periods=bool(f["periods"]),
                                      hypermeter=bool(f["hypermeter"]),
                                      bass_inversions=bool(f["bass_inversions"]))
            elif command[0] == "key":
                self.engine.request_key(command[1], urgent=command[2])

    def _apply_automation(self) -> None:
        """If an automation curve is active, set affect from it for the bar the
        engine is about to generate (engine.state.bar), looping if configured."""
        if self._automation is None:
            return
        curve, loop = self._automation
        bar = self.engine.state.bar
        if loop and loop > 0:
            bar %= loop
        self.engine.set_affect(**affect_at(curve, bar))

    def run(self) -> None:
        import numpy as np
        import signalflow as sf
        try:
            import sounddevice as sd
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("realtime playback needs sounddevice "
                               "(pip install -e '.[playground]')") from exc

        try:
            sr = int(sd.query_devices(kind="output")["default_samplerate"])
        except Exception:  # noqa: BLE001
            sr = 48000
        block = 512  # ~11 ms at 48 kHz: control/onset granularity, ample render headroom
        graph = sf.AudioGraph(output_device=sf.AudioOut_Dummy(2, sr, block), start=False)
        stream = sd.OutputStream(samplerate=sr, channels=2, dtype="float32", blocksize=block)
        try:
            console = Console(graph, self.config or ConsoleConfig())
            self.console = console
            bar_quarters = self.engine.config.meter.bar_quarters
            clock = BeatClock(0.0)  # beat -> second map only; `pos` is the frame clock
            lead_frames = int(self.lead_seconds * sr)
            heap: list[tuple[int, int, int, object]] = []    # (frame, kind, seq, payload)
            active: list[tuple[int, int, str, object]] = []  # (end_frame, seq, layer, node)
            seq = 0
            next_bar = 0
            pos = 0

            def generate_ahead() -> None:
                nonlocal seq, next_bar
                while (int(clock.time_at(next_bar * bar_quarters) * sr) < pos + lead_frames
                       and (self.max_bars is None or next_bar < self.max_bars)):
                    self._apply_pending()
                    self._apply_automation()
                    result = self.engine.advance_bar()
                    for beat, bpm in result.tempo_points:
                        clock.add_tempo_point(beat, bpm)
                    heapq.heappush(heap, (int(clock.time_at(next_bar * bar_quarters) * sr),
                                          _KIND_PARAMS, seq, result))
                    seq += 1
                    for ev in result.events:
                        on = clock.time_at(ev.start)
                        heapq.heappush(heap, (int(on * sr), _KIND_NOTE, seq,
                                              (ev, clock.time_at(ev.end) - on)))
                        seq += 1
                    next_bar += 1

            # jump-to-bar: deterministically fast-forward the engine to the seek
            # target with no audio (generation is µs-cheap); the frame clock
            # stays 0-based so playback begins immediately at that bar.
            while self.engine.state.bar < self.start_bar and not self._stop.is_set():
                self._apply_automation()
                self.engine.advance_bar()

            stream.start()
            while not self._stop.is_set():
                self._apply_pending()  # ~11 ms cadence: live control lands within a block
                if self._pending_config is not None:
                    # structural console change: rebuild on a fresh graph (a
                    # brief gap). Single-threaded, so this can't race the audio;
                    # the engine position is untouched and last params re-applied.
                    new_cfg = self._pending_config
                    self._pending_config = None
                    self.console = None
                    active.clear()  # old voices died with the old graph
                    graph.destroy()
                    graph = sf.AudioGraph(output_device=sf.AudioOut_Dummy(2, sr, block), start=False)
                    console = Console(graph, new_cfg)
                    self.config = new_cfg
                    self.console = console
                    if self._last_result is not None:
                        r = self._last_result
                        console.apply_params(r.params, r.affect, r.params.tempo_bpm,
                                             bar_seconds=bar_quarters * 60.0 / r.params.tempo_bpm)
                generate_ahead()

                while heap and heap[0][0] <= pos:
                    _, kind, _, payload = heapq.heappop(heap)
                    if kind == _KIND_PARAMS:
                        self._last_result = payload
                        console.apply_params(payload.params, payload.affect, payload.params.tempo_bpm,
                                             bar_seconds=bar_quarters * 60.0 / payload.params.tempo_bpm)
                        self.bars_played += 1
                        if self.on_bar is not None:
                            self.on_bar(payload)
                    else:
                        ev, dur_seconds = payload
                        layer, node, total = console.note_on(ev, dur_seconds)
                        heapq.heappush(active, (pos + int(total * sr), seq, layer, node))
                        seq += 1
                while active and active[0][0] <= pos:
                    _, _, layer, node = heapq.heappop(active)
                    console.remove(layer, node)

                # render one block and hand cooked samples to the device; the
                # blocking write paces us to realtime. Nothing else ever touches
                # the graph, so there is no mutation/render race.
                graph.render(block)
                samples = np.asarray(console.master.output_buffer)
                stream.write(np.ascontiguousarray(samples.T, dtype=np.float32))
                pos += block

                if (self.max_bars is not None and next_bar >= self.max_bars
                        and not heap and not active):
                    break
        finally:
            self.console = None
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            graph.destroy()
