import time

import pytest

pytest.importorskip("rtmidi")

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.live import BeatClock, LivePlayer, schedule_bar
from musicgen.midi_io import LAYER_MIDI


def test_beatclock_constant_tempo():
    clock = BeatClock(start_time=10.0, initial_bpm=120.0)
    assert clock.time_at(0.0) == 10.0
    assert clock.time_at(4.0) == 10.0 + 4 * 0.5  # 120 BPM = 0.5 s/beat


def test_beatclock_tempo_changes():
    clock = BeatClock(start_time=0.0, initial_bpm=60.0)
    clock.add_tempo_point(0.0, 120.0)      # replace at same beat
    clock.add_tempo_point(4.0, 60.0)       # slow down after bar 1
    assert clock.time_at(4.0) == pytest.approx(2.0)   # 4 beats at 120
    assert clock.time_at(6.0) == pytest.approx(4.0)   # +2 beats at 60
    with pytest.raises(ValueError):
        clock.add_tempo_point(2.0, 90.0)   # behind the last anchor


def test_schedule_bar_pairs_and_channels():
    engine = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(valence=0.2, energy=0.7, tension=0.3)
    result = engine.advance_bar()
    clock = BeatClock(start_time=0.0)
    entries = schedule_bar(result, clock, bar_quarters=4.0)

    midi = [e for e in entries if e.kind == "midi"]
    ons = [e for e in midi if e.payload.type == "note_on"]
    offs = [e for e in midi if e.payload.type == "note_off"]
    assert len(ons) == len(offs) == len(result.events)
    assert all(e.time >= 0.0 for e in midi)
    valid_channels = {spec.channel for spec in LAYER_MIDI.values()}
    assert {e.payload.channel for e in midi} <= valid_channels
    bar_markers = [e for e in entries if e.kind == "bar"]
    assert len(bar_markers) == 1 and bar_markers[0].payload is result


def test_schedule_respects_tempo_map():
    engine = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(energy=0.1)
    clock = BeatClock(start_time=0.0)
    schedule_bar(engine.advance_bar(), clock, bar_quarters=4.0)
    slow_bar_end = clock.time_at(4.0)
    engine2 = MusicEngine(seed=3, config=EngineConfig(mapper=MappingTable()))
    engine2.set_affect(energy=1.0)
    clock2 = BeatClock(start_time=0.0)
    schedule_bar(engine2.advance_bar(), clock2, bar_quarters=4.0)
    fast_bar_end = clock2.time_at(4.0)
    assert fast_bar_end < slow_bar_end


class FakePort:
    def __init__(self):
        self.messages = []
        self.t0 = time.monotonic()

    def send(self, msg):
        self.messages.append((time.monotonic() - self.t0, msg))


def test_live_player_smoke_two_bars():
    engine = MusicEngine(seed=5, config=EngineConfig(mapper=MappingTable()))
    engine.set_affect(valence=0.0, energy=0.9, tension=0.3)
    engine.set_override("tempo_bpm", 240.0)  # keep the test fast: 1 s/bar
    port = FakePort()
    played = []
    player = LivePlayer(engine, port, prime_seconds=0.05,
                        on_bar=lambda r: played.append(r.bar), max_bars=2)
    player.set_affect(tension=0.9)  # queued command must apply, not crash
    player.start()
    player._thread.join(timeout=6.0)
    assert not player._thread.is_alive(), "player did not finish"

    notes = [(t, m) for t, m in port.messages if m.type in ("note_on", "note_off")]
    ons = [m for _, m in notes if m.type == "note_on"]
    assert len(ons) > 20, "expected a full-texture bar of notes"
    assert played == [0, 1]
    assert engine.affect.tension == 0.9

    # deadlines roughly honored: first on near prime offset, last within ~2.3s
    first_on = min(t for t, m in notes if m.type == "note_on")
    assert first_on < 0.5
    assert max(t for t, _ in notes) < 3.5
    # teardown sent all-notes-off on every used channel
    cc123 = {m.channel for _, m in port.messages if m.type == "control_change" and m.control == 123}
    assert cc123 == {spec.channel for spec in LAYER_MIDI.values()}


def test_virtual_port_roundtrip():
    import mido
    try:
        out = mido.open_output("musicgen-test", virtual=True)
    except Exception:
        pytest.skip("no ALSA sequencer available")
    out.send(mido.Message("note_on", note=60, velocity=1))
    out.close()
