"""BeatClock: absolute beats -> wall/render seconds through an incrementally
extended, piecewise-constant tempo map. Shared by the MIDI live player and
the synthesis renderers; deliberately dependency-free.
"""

from __future__ import annotations


class BeatClock:
    def __init__(self, start_time: float, initial_bpm: float = 100.0) -> None:
        self._anchors: list[tuple[float, float, float]] = [(0.0, start_time, initial_bpm)]

    def add_tempo_point(self, beat: float, bpm: float) -> None:
        b0, t0, bpm0 = self._anchors[-1]
        if beat < b0 - 1e-9:
            raise ValueError(f"tempo point at beat {beat} precedes anchor {b0}")
        if abs(beat - b0) < 1e-9:
            self._anchors[-1] = (b0, t0, bpm)
            return
        self._anchors.append((beat, t0 + (beat - b0) * 60.0 / bpm0, bpm))

    def time_at(self, beat: float) -> float:
        for b0, t0, bpm0 in reversed(self._anchors):
            if beat >= b0 - 1e-9:
                return t0 + (beat - b0) * 60.0 / bpm0
        b0, t0, bpm0 = self._anchors[0]
        return t0 + (beat - b0) * 60.0 / bpm0

    @property
    def current_bpm(self) -> float:
        return self._anchors[-1][2]
