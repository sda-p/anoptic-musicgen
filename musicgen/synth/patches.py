"""Voice designs: one subtractive/FM patch per layer, drum synthesis per GM
pitch (PLANS.md M6 / SYNTHESIS.md).

Each builder returns (root_node, total_seconds). Voices are plain node
chains with explicit lifecycles — the renderer detaches them from their strip
bus after total_seconds, mirroring how a C engine's voice allocator works
(no garbage-collected voices in real life).

Techniques exercised, deliberately spanning the authored-production
vocabulary: detuned unison, sub-oscillator layering, filter envelopes,
delayed vibrato LFO, 2-operator FM, pitch-envelope drums, filtered noise
percussion, velocity->amplitude/cutoff coupling.

Durations arrive in SECONDS (the renderer converts beats through the tempo
map). Shared control nodes (per-layer cutoff Smooths) come from the console
so one lever retargets every sounding voice.
"""

from __future__ import annotations

import signalflow as sf


def pad_voice(freq: float, amp: float, dur: float, cutoff) -> tuple[object, float]:
    """Three detuned saws -> lowpass -> slow envelope."""
    detune = 1.004
    osc = (
        sf.SawOscillator(freq)
        + sf.SawOscillator(freq * detune)
        + sf.SawOscillator(freq / detune)
    ) * (1.0 / 3.0)
    attack = min(0.5, dur * 0.35)
    release = 0.8
    env = sf.ASREnvelope(attack, max(dur - attack, 0.05), release, curve=1.5)
    filt = sf.SVFilter(osc, "low_pass", cutoff=cutoff, resonance=0.15)
    return sf.StereoPanner(filt * env * amp, 0.0), dur + release


def bass_voice(freq: float, amp: float, dur: float, cutoff) -> tuple[object, float]:
    """Saw + sub-octave sine, plucky filter envelope."""
    body = sf.SawOscillator(freq) * 0.6 + sf.SineOscillator(freq * 0.5) * 0.5
    env = sf.ASREnvelope(0.004, max(dur - 0.004, 0.03), 0.1, curve=2.0)
    filter_env = sf.ASREnvelope(0.001, 0.05, 0.25, curve=3.0)
    filt = sf.SVFilter(body, "low_pass", cutoff=cutoff * (0.35 + filter_env * 0.65), resonance=0.2)
    return sf.StereoPanner(filt * env * amp, 0.0), dur + 0.1


def lead_voice(freq: float, amp: float, dur: float, cutoff) -> tuple[object, float]:
    """Triangle/saw blend with delayed vibrato."""
    vibrato = 1.0 + sf.SineOscillator(5.5) * (sf.Line(0.0, 1.0, 0.35) * 0.006)
    osc = sf.TriangleOscillator(freq * vibrato) * 0.7 + sf.SawOscillator(freq * vibrato) * 0.25
    env = sf.ASREnvelope(0.02, max(dur - 0.02, 0.03), 0.18, curve=1.8)
    filt = sf.SVFilter(osc, "low_pass", cutoff=cutoff, resonance=0.1)
    return sf.StereoPanner(filt * env * amp, 0.12), dur + 0.18


def arp_voice(freq: float, amp: float, dur: float) -> tuple[object, float]:
    """2-operator FM pluck (bell-ish 3:1 ratio, fast-decaying index)."""
    mod_env = sf.ASREnvelope(0.001, 0.0, min(dur, 0.35), curve=4.0)
    modulator = sf.SineOscillator(freq * 3.007) * freq * 1.8 * mod_env
    carrier = sf.SineOscillator(freq + modulator)
    sustain = max(dur * 0.5, 0.02)
    release = min(dur, 0.3)
    env = sf.ASREnvelope(0.002, sustain, release, curve=3.0)
    return sf.StereoPanner(carrier * env * amp, -0.2), 0.002 + sustain + release


# --- drums (keyed by GM pitch, matching gen/perc.py's DRUMS map) -------------

def _kick(amp: float) -> tuple[object, float]:
    pitch_env = sf.ASREnvelope(0.0005, 0.0, 0.09, curve=4.0)
    body = sf.SineOscillator(44 + pitch_env * 85)
    click = (
        sf.SVFilter(sf.WhiteNoise(), "band_pass", cutoff=3500, resonance=0.4)
        * sf.ASREnvelope(0.0005, 0.0, 0.012, curve=3.0) * 0.5
    )
    env = sf.ASREnvelope(0.001, 0.02, 0.22, curve=3.0)
    return sf.StereoPanner((body + click) * env * amp * 1.2, 0.0), 0.30


def _snare(amp: float) -> tuple[object, float]:
    rattle = (
        sf.SVFilter(sf.WhiteNoise(), "band_pass", cutoff=1900, resonance=0.3)
        * sf.ASREnvelope(0.001, 0.01, 0.16, curve=3.0) * 0.8
    )
    tone = sf.SineOscillator(195) * sf.ASREnvelope(0.001, 0.0, 0.08, curve=3.0) * 0.4
    return sf.StereoPanner((rattle + tone) * amp, 0.04), 0.22


def _rim(amp: float) -> tuple[object, float]:
    hit = (
        sf.SVFilter(sf.WhiteNoise(), "band_pass", cutoff=4500, resonance=0.6)
        * sf.ASREnvelope(0.0005, 0.0, 0.045, curve=3.0)
    )
    return sf.StereoPanner(hit * amp, 0.1), 0.06


def _hat(amp: float, open_hat: bool) -> tuple[object, float]:
    decay = 0.28 if open_hat else 0.045
    noise = (
        sf.SVFilter(sf.WhiteNoise(), "high_pass", cutoff=7800, resonance=0.2)
        * sf.ASREnvelope(0.001, 0.005 if open_hat else 0.0, decay, curve=3.0)
    )
    return sf.StereoPanner(noise * amp * 0.7, -0.22), decay + 0.03


def _tom(freq: float):
    def build(amp: float) -> tuple[object, float]:
        pitch_env = sf.ASREnvelope(0.001, 0.0, 0.18, curve=3.0)
        body = sf.SineOscillator(freq * (1.0 + pitch_env * 0.55))
        thump = sf.WhiteNoise() * sf.ASREnvelope(0.0005, 0.0, 0.02, curve=3.0) * 0.2
        env = sf.ASREnvelope(0.001, 0.02, 0.30, curve=2.5)
        return sf.StereoPanner((body + thump) * env * amp, 0.0), 0.36
    return build


def _crash(amp: float) -> tuple[object, float]:
    wash = sf.SVFilter(sf.WhiteNoise(), "high_pass", cutoff=5200, resonance=0.1)
    shimmer = sf.SVFilter(sf.WhiteNoise(), "band_pass", cutoff=9000, resonance=0.6) * 0.5
    env = sf.ASREnvelope(0.002, 0.05, 1.3, curve=2.5)
    return sf.StereoPanner((wash + shimmer) * env * amp * 0.6, 0.15), 1.45


def _shaker(amp: float) -> tuple[object, float]:
    noise = (
        sf.SVFilter(sf.WhiteNoise(), "band_pass", cutoff=6300, resonance=0.5)
        * sf.ASREnvelope(0.015, 0.0, 0.06, curve=1.5)
    )
    return sf.StereoPanner(noise * amp * 0.6, -0.3), 0.10


DRUM_BUILDERS = {
    36: _kick,
    37: _rim,
    38: _snare,
    42: lambda amp: _hat(amp, open_hat=False),
    46: lambda amp: _hat(amp, open_hat=True),
    45: _tom(105.0),
    47: _tom(135.0),
    50: _tom(170.0),
    49: _crash,
    70: _shaker,
}


def drum_voice(pitch: int, amp: float) -> tuple[object, float]:
    builder = DRUM_BUILDERS.get(pitch)
    if builder is None:
        return _rim(amp)  # unmapped percussion: audible, harmless
    return builder(amp)
