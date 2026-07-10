"""Voice designs: one subtractive/FM patch per layer, drum synthesis per GM
pitch (PLANS.md M6 / SYNTHESIS.md).

Each builder returns (root_node, total_seconds). Voices are plain node
chains with explicit lifecycles — the renderer detaches them from their strip
bus after total_seconds, mirroring how a C engine's voice allocator works
(no garbage-collected voices in real life).

Techniques exercised, deliberately spanning the authored-production
vocabulary: detuned unison (stereo-spread in the bright pad), sub-oscillator
layering, filter envelopes, per-voice cutoff keytracking, delayed vibrato
LFO, 2-operator FM, pitch-envelope drums, filtered noise percussion,
velocity->amplitude coupling.

Durations arrive in SECONDS (the renderer converts beats through the tempo
map). Shared control nodes (per-layer cutoff Smooths) come from the console
so one lever retargets every sounding voice.
"""

from __future__ import annotations

import signalflow as sf


def _keytrack(freq: float, amount: float) -> float:
    """Cutoff keytracking factor: 1.0 at middle C, rising/falling with pitch
    so brightness stays even across the register. A scalar — pitch is known
    at allocation, so tracking costs nothing at render time."""
    return min(2.5, max(0.5, (freq / 261.63) ** amount))


def _noise(seed: int):
    """Seeded white noise. signalflow's stochastic nodes otherwise seed from
    a global entropy pool, making renders irreproducible (SYNTHESIS.md
    finding 8). Fixed per-role seeds also mean every kick/snare transient is
    identical — drum-machine consistency; Humanize supplies the variation."""
    noise = sf.WhiteNoise()
    noise.set_seed(seed)
    return noise


# --- shared sample/wavetable resources (built per console, numpy-synthesized:
# --- no recorded assets, but the machinery is the real sampler machinery) ----

WAVETABLE_FRAMES = 4
SAMPLE_ROOT_MIDI = 72  # the bell sample's native pitch (C5)


def make_wavetable_bank():
    """Buffer2D of single-cycle frames morphing dark -> bright: harmonic n at
    1/n^k with k falling per frame, odd harmonics leading. Built once per
    console; Wavetable2D's crossfade input scans it at audio rate."""
    import numpy as np

    frames = []
    n = 2048
    t = np.arange(n) / n
    for f in range(WAVETABLE_FRAMES):
        rolloff = 2.3 - 0.45 * f
        wave = np.zeros(n)
        for h in range(1, 24):
            amp = 1.0 / h ** rolloff
            if h % 2 == 0:
                amp *= 0.35 + 0.2 * f  # even harmonics fade in across frames
            wave += amp * np.sin(2 * np.pi * h * t)
        wave *= 0.9 / np.abs(wave).max()
        frames.append(sf.Buffer([wave.astype(np.float32)]))
    return sf.Buffer2D(frames)


def make_bell_sample(sample_rate: int):
    """A struck-bell 'recording' synthesized into a Buffer: inharmonic
    partials (tubular-bell ratios) with independent decays and a noise chiff.
    Deterministic, so renders stay bit-reproducible."""
    import numpy as np

    dur = 1.6
    n = int(dur * sample_rate)
    t = np.arange(n) / sample_rate
    f0 = 440.0 * 2.0 ** ((SAMPLE_ROOT_MIDI - 69) / 12.0)
    partials = ((1.0, 1.0, 1.9), (2.76, 0.6, 3.2), (5.40, 0.25, 4.8), (8.93, 0.12, 7.0))
    wave = np.zeros(n)
    for ratio, amp, decay in partials:
        wave += amp * np.sin(2 * np.pi * f0 * ratio * t) * np.exp(-decay * t)
    rng = np.random.default_rng(0xBE11)
    chiff = rng.standard_normal(int(0.012 * sample_rate)) * np.linspace(1, 0, int(0.012 * sample_rate))
    wave[: chiff.size] += chiff * 0.4
    wave *= 0.8 / np.abs(wave).max()
    buf = sf.Buffer(1, n)
    buf.data[0][:] = wave.astype(np.float32)
    return buf


def wavetable_pad_voice(freq: float, amp: float, dur: float, cutoff, bank) -> tuple[object, float]:
    """Morphing wavetable pad: the crossfade input scans the bank dark ->
    bright over the note (audio-rate timbre automation inside the voice).
    crossfade is NORMALIZED 0..1 across the bank and its edge reads are
    unguarded in signalflow (>1.0 segfaults) — clamp hard, always."""
    morph = sf.ASREnvelope(min(1.2, max(0.3, dur * 0.6)), max(dur - 1.2, 0.05), 1.0, curve=1.2)
    osc = sf.Wavetable2D(bank, freq, crossfade=sf.Clip(morph * min(1.0, amp * 1.4), 0.0, 0.999))
    attack = min(0.4, dur * 0.35)
    release = 0.9
    env = sf.ASREnvelope(attack, max(dur - attack, 0.05), release, curve=1.5)
    filt = sf.SVFilter(osc, "low_pass", cutoff=cutoff * 1.2 * _keytrack(freq, 0.2), resonance=0.12)
    return sf.StereoPanner(filt * env * amp * 0.8, 0.0), dur + release


def sampler_voice(pitch: int, amp: float, dur: float, cutoff, sample, sample_rate: int,
                  root_midi: int = SAMPLE_ROOT_MIDI, rate_scale: float = 1.0) -> tuple[object, float]:
    """Sampled voice repitched from its root key: rate = 2^(dn/12), so higher
    notes ring shorter and brighter — the honest resampling artifact. The
    lever-driven filter still applies (sampled layers obey the same levers).
    root_midi is the sample's native pitch; rate_scale corrects a sample-rate
    mismatch (file_sr / graph_sr) — 1.0 for the graph-native bell."""
    rate = 2.0 ** ((pitch - root_midi) / 12.0) * rate_scale
    natural = sample.num_frames / sample_rate / rate
    player = sf.BufferPlayer(sample, rate=rate, loop=False)
    total = min(natural, dur + 1.2)
    env = sf.ASREnvelope(0.001, max(total - 0.4, 0.02), 0.4, curve=2.0)
    filt = sf.SVFilter(player, "low_pass",
                       cutoff=cutoff * 1.5 * _keytrack(440.0 * 2 ** ((pitch - 69) / 12), 0.2),
                       resonance=0.0)
    return sf.StereoPanner(filt * env * amp, 0.08), total


def pad_voice(freq: float, amp: float, dur: float, cutoff, variant: str = "warm") -> tuple[object, float]:
    """Three detuned saws -> lowpass -> slow envelope. "bright": the unison
    voices spread across the stereo field (per-voice pan at allocation),
    wider detune, hotter resonant cutoff, faster bloom — same topology, new
    preset (instrument swaps are presets, not new DSP)."""
    bright = variant == "bright"
    detune = 1.009 if bright else 1.004
    saws = (sf.SawOscillator(freq), sf.SawOscillator(freq * detune), sf.SawOscillator(freq / detune))
    if bright:  # stereo unison spread: center anchor, detuned voices at the edges
        osc = sum(sf.StereoPanner(saw, pan) for saw, pan in zip(saws, (0.0, -0.7, 0.7))) * (1.0 / 3.0)
    else:
        osc = sum(saws) * (1.0 / 3.0)
    attack = min(0.15 if bright else 0.5, dur * 0.35)
    release = 0.8
    env = sf.ASREnvelope(attack, max(dur - attack, 0.05), release, curve=1.5)
    filt = sf.SVFilter(osc, "low_pass",
                       cutoff=cutoff * (1.7 if bright else 1.0) * _keytrack(freq, 0.2),
                       resonance=0.32 if bright else 0.15)
    out = filt * env * amp
    return (out if bright else sf.StereoPanner(out, 0.0)), dur + release


def bass_voice(freq: float, amp: float, dur: float, cutoff, variant: str = "round") -> tuple[object, float]:
    """Saw + sub-octave sine, plucky filter envelope. "driven": tanh pre-drive
    and a deeper, hotter filter sweep."""
    driven = variant == "driven"
    body = sf.SawOscillator(freq) * 0.6 + sf.SineOscillator(freq * 0.5) * 0.5
    if driven:
        body = sf.Tanh(body * 2.2) * 0.8
    env = sf.ASREnvelope(0.004, max(dur - 0.004, 0.03), 0.1, curve=2.0)
    filter_env = sf.ASREnvelope(0.001, 0.05, 0.25, curve=3.0)
    sweep = (0.25 + filter_env * 1.05) if driven else (0.35 + filter_env * 0.65)
    filt = sf.SVFilter(body, "low_pass",
                       cutoff=cutoff * sweep * (1.4 if driven else 1.0) * _keytrack(freq, 0.3),
                       resonance=0.3 if driven else 0.2)
    return sf.StereoPanner(filt * env * amp, 0.0), dur + 0.1


def lead_voice(freq: float, amp: float, dur: float, cutoff, variant: str = "soft") -> tuple[object, float]:
    """Triangle/saw blend with delayed vibrato. "hard": saw/square stack,
    earlier and deeper vibrato, snappier attack, hotter resonant filter.
    "mellow" (the C5 countermelody): triangle-dominant with a sine sub, later
    and shallower vibrato, slower attack, darker filter — and panned opposite
    the melody, so the two lines separate spatially."""
    hard = variant == "hard"
    mellow = variant == "mellow"
    vibrato = 1.0 + sf.SineOscillator(6.2 if hard else 4.8 if mellow else 5.5) * (
        sf.Line(0.0, 1.0, 0.15 if hard else 0.5 if mellow else 0.35)
        * (0.009 if hard else 0.004 if mellow else 0.006))
    if hard:
        osc = sf.SawOscillator(freq * vibrato) * 0.6 + sf.SquareOscillator(freq * vibrato) * 0.3
    elif mellow:
        osc = sf.TriangleOscillator(freq * vibrato) * 0.8 + sf.SineOscillator(freq * vibrato) * 0.2
    else:
        osc = sf.TriangleOscillator(freq * vibrato) * 0.7 + sf.SawOscillator(freq * vibrato) * 0.25
    attack = 0.006 if hard else 0.035 if mellow else 0.02
    env = sf.ASREnvelope(attack, max(dur - attack, 0.03), 0.22 if mellow else 0.18, curve=1.8)
    filt = sf.SVFilter(osc, "low_pass",
                       cutoff=cutoff * (1.4 if hard else 0.8 if mellow else 1.0)
                       * _keytrack(freq, 0.4),
                       resonance=0.2 if hard else 0.1)
    return sf.StereoPanner(filt * env * amp, -0.14 if mellow else 0.12), dur + 0.18


def arp_voice(freq: float, amp: float, dur: float, variant: str = "pluck") -> tuple[object, float]:
    """2-operator FM pluck. "pluck": bell-ish 3:1 ratio, fast-decaying index;
    "glass": inharmonic 7:1 ratio, hotter index, longer shimmer."""
    glass = variant == "glass"
    ratio, index = (7.003, 2.6) if glass else (3.007, 1.8)
    mod_env = sf.ASREnvelope(0.001, 0.0, min(dur, 0.5 if glass else 0.35), curve=4.0)
    modulator = sf.SineOscillator(freq * ratio) * freq * index * mod_env
    carrier = sf.SineOscillator(freq + modulator)
    sustain = max(dur * 0.5, 0.02)
    release = min(dur, 0.5 if glass else 0.3)
    env = sf.ASREnvelope(0.002, sustain, release, curve=3.0)
    return sf.StereoPanner(carrier * env * amp, -0.2), 0.002 + sustain + release


# --- environmental / texture voices (Music Ticket DX-1413a) ------------------
# Note-triggered like every other voice: a texture sounds for the duration of
# whatever note its layer plays (long pad chords -> long washes; a busy arp ->
# a flurry of chimes). Timbre rides the affect levers (the energy/tension
# Smooth nodes passed in, exactly as the subtractive voices tap the cutoff),
# and every noise source is seeded, so renders stay deterministic. They live
# OUTSIDE the energy instrument tiers (control/mapping.py) — opt-in per layer
# via the playground picker — so the default orchestration is untouched.

def chime_voice(pitch: int, freq: float, amp: float, dur: float, cutoff) -> tuple[object, float]:
    """Wind chimes: additive inharmonic metal-tube partials (tubular-bell
    ratios) each with its own decay, so the top partials die first over a soft
    strike chiff. Rings well past the note. Pan scatters deterministically by
    pitch, so a run of chimes spreads across the field like a real set."""
    ratios = (1.0, 2.76, 5.40, 8.93, 11.34)
    decays = (1.0, 1.7, 2.6, 3.8, 5.2)   # higher partials ring shorter
    gains = (1.0, 0.6, 0.35, 0.2, 0.12)
    ring = min(dur + 1.6, 2.6)
    body = None
    for ratio, decay, gain in zip(ratios, decays, gains):
        partial = sf.SineOscillator(freq * ratio) * (
            gain * sf.ASREnvelope(0.001, 0.0, max(ring / decay, 0.05), curve=3.0))
        body = partial if body is None else body + partial
    chiff = (sf.SVFilter(_noise(0xC41E), "band_pass", cutoff=5200, resonance=0.4)
             * sf.ASREnvelope(0.0005, 0.0, 0.02, curve=3.0) * 0.3)
    filt = sf.SVFilter(body + chiff, "low_pass",
                       cutoff=cutoff * 1.3 * _keytrack(freq, 0.2), resonance=0.05)
    pan = ((pitch * 7) % 11) / 11.0 * 1.2 - 0.6   # deterministic scatter in -0.6..0.6
    return sf.StereoPanner(filt * amp * 0.6, pan), ring + 0.1


def breeze_voice(freq: float, amp: float, dur: float, cutoff, energy) -> tuple[object, float]:
    """Sound of the breeze: two decorrelated noise streams band-passed into an
    airy wash, breathing on a slow gust LFO with a faster rustle on top, under a
    soft swell in and out. energy (a lever node) lifts the band brighter and
    louder as things pick up — a light air vs. a gusty wind."""
    total = dur + 1.4
    swell = sf.ASREnvelope(0.6, max(dur - 0.6, 0.05), 0.9, curve=1.4)
    gust = 0.55 + 0.45 * (sf.SineOscillator(0.13) * 0.5 + 0.5)     # ~8 s breathing
    flutter = 0.85 + 0.15 * (sf.SineOscillator(0.9) * 0.5 + 0.5)   # leaf rustle
    center = sf.Clip(360.0 + energy * 1400.0, 200.0, 3000.0)
    air = sf.Clip(0.25 + energy * 0.4, 0.2, 0.7)

    def side(seed: int, mult: float):
        band = sf.SVFilter(_noise(seed), "band_pass", cutoff=center * mult, resonance=0.12)
        return sf.SVFilter(band, "high_pass", cutoff=180.0, resonance=0.0)  # trim rumble

    wash = sf.StereoPanner(side(0xB4EE, 1.0), -0.6) + sf.StereoPanner(side(0xB4EF, 1.18), 0.6)
    return wash * gust * flutter * swell * amp * air, total


def whistle_voice(freq: float, amp: float, dur: float, cutoff, energy) -> tuple[object, float]:
    """Whistle of wind through the trees: a resonant band-pass 'sings' at the
    note pitch (noise excitation -> a tonal whistle), sweetened by a soft sine
    so it whistles the line, over a breath bed — the whole thing wavering on a
    slow random pitch drift like wind through branches. Breath rises with
    energy."""
    total = dur + 0.6
    drift = (1.0 + sf.SineOscillator(0.7) * 0.012
             + sf.Smooth(sf.SampleAndHold(_noise(0x5A11), sf.Impulse(2.5)), 0.999) * 0.03)
    sung = sf.SVFilter(_noise(0x5A12), "band_pass",
                       cutoff=sf.Clip(freq * drift, 60.0, 8000.0), resonance=0.9) * 1.3
    tone = sf.SineOscillator(freq * drift) * 0.35
    breath = (sf.SVFilter(_noise(0x5A13), "high_pass", cutoff=2400.0, resonance=0.1)
              * sf.Clip(0.1 + energy * 0.25, 0.05, 0.4))
    env = sf.ASREnvelope(0.12, max(dur - 0.12, 0.05), 0.4, curve=1.5)
    filt = sf.SVFilter(sung + tone + breath, "low_pass", cutoff=cutoff * 1.2, resonance=0.0)
    return sf.StereoPanner(filt * env * amp * 0.7, 0.1), total


def bad_ground_voice(freq: float, amp: float, dur: float, cutoff, tension) -> tuple[object, float]:
    """Bad ground: a ~60 Hz mains hum gone wrong — buzzy (square + a saw
    harmonic), flickering on a bad contact (slow random AM), with intermittent
    high crackle/'psssht' bursts whose rate rides tension. Pitch nudges the hum
    slightly so bass notes aren't identical, but it stays anchored low like real
    mains hum."""
    total = dur + 0.2
    nudge = min(1.5, max(0.7, freq / 65.0))
    fundamental = 60.0 * nudge
    hum = sf.SVFilter(sf.SquareOscillator(fundamental) * 0.5
                      + sf.SawOscillator(fundamental * 2.0) * 0.22,
                      "low_pass", cutoff=760.0, resonance=0.35)
    buzz = sf.SVFilter(hum, "band_pass", cutoff=1500.0, resonance=0.7) * 0.35
    flicker = 0.6 + 0.4 * sf.Smooth(sf.SampleAndHold(_noise(0x6404), sf.Impulse(7.0)), 0.995)
    sparks = sf.RandomImpulse(3.0 + tension * 14.0)  # crackle rate rides tension
    sparks.set_seed(0x6405)
    crackle = (sf.SVFilter(_noise(0x6406), "high_pass", cutoff=3200.0, resonance=0.2)
               * sf.Smooth(sparks, 0.9) * sf.Clip(0.4 + tension * 0.5, 0.3, 0.95))
    env = sf.ASREnvelope(0.004, max(dur - 0.004, 0.02), 0.12, curve=2.0)
    body = (hum + buzz) * flicker + crackle
    filt = sf.SVFilter(body, "low_pass", cutoff=sf.Clip(cutoff * 2.0, 400.0, 6000.0), resonance=0.0)
    return sf.StereoPanner(filt * env * amp * 0.8, 0.0), total


# --- drums (keyed by GM pitch, matching gen/perc.py's DRUMS map) -------------

def _kick(amp: float) -> tuple[object, float]:
    pitch_env = sf.ASREnvelope(0.0005, 0.0, 0.09, curve=4.0)
    body = sf.SineOscillator(44 + pitch_env * 85)
    click = (
        sf.SVFilter(_noise(0xD1C4), "band_pass", cutoff=3500, resonance=0.4)
        * sf.ASREnvelope(0.0005, 0.0, 0.012, curve=3.0) * 0.5
    )
    env = sf.ASREnvelope(0.001, 0.02, 0.22, curve=3.0)
    return sf.StereoPanner((body + click) * env * amp * 1.2, 0.0), 0.30


def _snare(amp: float) -> tuple[object, float]:
    rattle = (
        sf.SVFilter(_noise(0xD5A2), "band_pass", cutoff=1900, resonance=0.3)
        * sf.ASREnvelope(0.001, 0.01, 0.16, curve=3.0) * 0.8
    )
    tone = sf.SineOscillator(195) * sf.ASREnvelope(0.001, 0.0, 0.08, curve=3.0) * 0.4
    return sf.StereoPanner((rattle + tone) * amp, 0.04), 0.22


def _rim(amp: float) -> tuple[object, float]:
    hit = (
        sf.SVFilter(_noise(0xD814), "band_pass", cutoff=4500, resonance=0.6)
        * sf.ASREnvelope(0.0005, 0.0, 0.045, curve=3.0)
    )
    return sf.StereoPanner(hit * amp, 0.1), 0.06


def _hat(amp: float, open_hat: bool) -> tuple[object, float]:
    decay = 0.28 if open_hat else 0.045
    noise = (
        sf.SVFilter(_noise(0xDCA7), "high_pass", cutoff=7800, resonance=0.2)
        * sf.ASREnvelope(0.001, 0.005 if open_hat else 0.0, decay, curve=3.0)
    )
    return sf.StereoPanner(noise * amp * 0.7, -0.22), decay + 0.03


def _tom(freq: float):
    def build(amp: float) -> tuple[object, float]:
        pitch_env = sf.ASREnvelope(0.001, 0.0, 0.18, curve=3.0)
        body = sf.SineOscillator(freq * (1.0 + pitch_env * 0.55))
        thump = _noise(0xD703) * sf.ASREnvelope(0.0005, 0.0, 0.02, curve=3.0) * 0.2
        env = sf.ASREnvelope(0.001, 0.02, 0.30, curve=2.5)
        return sf.StereoPanner((body + thump) * env * amp, 0.0), 0.36
    return build


def _crash(amp: float) -> tuple[object, float]:
    wash = sf.SVFilter(_noise(0xDC4A), "high_pass", cutoff=5200, resonance=0.1)
    shimmer = sf.SVFilter(_noise(0xDC4B), "band_pass", cutoff=9000, resonance=0.6) * 0.5
    env = sf.ASREnvelope(0.002, 0.05, 1.3, curve=2.5)
    return sf.StereoPanner((wash + shimmer) * env * amp * 0.6, 0.15), 1.45


def _shaker(amp: float) -> tuple[object, float]:
    noise = (
        sf.SVFilter(_noise(0xD5AC), "band_pass", cutoff=6300, resonance=0.5)
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
