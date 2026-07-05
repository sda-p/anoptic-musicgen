"""The mixing console: per-strip 3-band EQ, bus chorus, send buses (FDN
reverb, tempo-synced ping-pong delay), sidechain ducking (schedule-driven or
audio-detected), and a master chain (drive -> glue compressor -> lookahead
limiter -> clip guard). Lever-mapped DSP parameters land on Smooth nodes, so
one retarget glides every dependent voice and bus (SYNTHESIS.md).

The reverb is a hand-rolled 4-line FDN with a Householder feedback matrix and
per-line damping filters INSIDE the loop — the thing the M6 Schroeder couldn't
express with stock delay nodes; it needs signalflow's feedback buffer pair,
whose loop delay must exceed one hardware block (SYNTHESIS.md finding 5).

Sidechain pumping defaults to schedule-driven (the renderer tells the console
when a kick fires — the symbolic layer already knows); sidechain="detect"
switches to an envelope follower on the drum strip, the technique needed when
the trigger source is audio you don't schedule.

M11 adds the voice-engine techniques: a declarative MOD MATRIX (shared LFO/
drift/lever sources summed per destination), GRANULAR SHIMMER (octave-up
grains from the pad strip's own recent past, tension-driven), an audio-rate
SWEEP envelope shaping big cutoff rises over a bar, and shared sampler/
wavetable resources handed to voices at allocation.
"""

from __future__ import annotations

from dataclasses import dataclass

import signalflow as sf

from musicgen.ir import NoteEvent
from musicgen.synth import patches


def _hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12.0)


@dataclass(frozen=True)
class ConsoleConfig:
    layer_trim: tuple[tuple[str, float], ...] = (
        ("pad", 0.60), ("bass", 0.85), ("melody", 0.70), ("arp", 0.55), ("perc", 0.95),
    )
    # per-strip 3-band EQ: (low_gain, mid_gain, high_gain, low_freq, high_freq),
    # linear gains — the classic channel-strip carve (bass owns the lows, pad
    # clears mud, melody/arp get presence and air, perc keeps thump and snap)
    strip_eq: tuple[tuple[str, tuple[float, float, float, float, float]], ...] = (
        ("pad", (0.85, 1.00, 1.05, 260.0, 3200.0)),
        ("bass", (1.12, 1.00, 0.80, 180.0, 2200.0)),
        ("melody", (0.80, 1.05, 1.15, 220.0, 3600.0)),
        ("arp", (0.60, 1.00, 1.20, 300.0, 4800.0)),
        ("perc", (1.15, 0.95, 1.10, 120.0, 5000.0)),
    )
    # bus chorus (dual-rate modulated taps, stereo): applied to these layers
    chorus_layers: tuple[str, ...] = ("pad",)
    chorus_mix: float = 0.35
    chorus_base: float = 0.016     # seconds
    chorus_depth: float = 0.004    # seconds of modulation
    chorus_rates: tuple[float, float] = (0.6, 0.73)  # Hz, L/R decorrelation
    reverb_layer_send: tuple[tuple[str, float], ...] = (
        ("pad", 1.00), ("bass", 0.10), ("melody", 0.75), ("arp", 0.90), ("perc", 0.30),
    )
    delay_layer_send: tuple[tuple[str, float], ...] = (
        ("pad", 0.00), ("bass", 0.00), ("melody", 1.00), ("arp", 0.80), ("perc", 0.00),
    )
    duck_layers: tuple[str, ...] = ("pad", "arp")
    sidechain: str = "schedule"    # "schedule" | "detect" (envelope follower on perc)
    detect_sensitivity: float = 6.0
    detect_release: float = 0.9995  # one-pole release on the follower
    velocity_curve: float = 1.5
    # FDN reverb: mutually inharmonic line delays (all must exceed one
    # hardware block — signalflow's feedback loop minimum), T60 decay target,
    # in-loop damping cutoff, output tone shelf
    fdn_delays: tuple[float, ...] = (0.0337, 0.0453, 0.0577, 0.0689)
    fdn_t60: float = 2.2
    fdn_damping_hz: float = 4200.0
    reverb_predelay: float = 0.02
    reverb_shelf_hz: float = 4500.0
    reverb_shelf_db: float = -4.0
    # ping-pong delay bus: per-side time is the tempo-synced Smooth (dotted
    # 8th); feedback applies per round trip
    delay_feedback: float = 0.42
    delay_max_seconds: float = 1.5
    master_makeup: float = 1.5
    # lookahead limiter: instant-attack |x| detector with one-pole release,
    # gain applied to a delayed copy so reduction leads the peak
    limiter_lookahead: float = 0.005
    limiter_ceiling: float = 0.92
    limiter_release: float = 0.9995
    # one-pole gain smoothing must converge within the lookahead; 0.98 leaves
    # ~1% of a step after 5 ms (a linear attack ramp would hit it exactly)
    limiter_gain_smooth: float = 0.98
    # granular shimmer: octave-up grains sprayed from the pad strip's recent
    # past into the reverb — the unsettled-air texture, riding the tension
    # lever (amount = shimmer_max * tension^2)
    shimmer_max: float = 0.35
    shimmer_grain_rate: float = 2.0       # per-grain repitch (octave up)
    shimmer_grain_duration: float = 0.12
    shimmer_history_seconds: float = 2.0
    # mod matrix: (source, destination, depth). Sources: lfo_slow, lfo_fast,
    # drift (smoothed sample&hold noise), tension, energy. Destinations:
    # cutoff (ratio: 1 + sum), width (additive, clipped), shimmer (additive).
    mod_matrix: tuple[tuple[str, str, float], ...] = (
        ("lfo_slow", "cutoff", 0.12),
        ("drift", "width", 0.12),
    )
    # audio-rate sweep automation: a big upward cutoff retarget swells over a
    # whole bar (retriggered envelope) instead of the one-pole's fixed-time
    # glide — same target, musically shaped arrival
    sweep_trigger_ratio: float = 1.6
    sweep_depth: float = 0.9


def _follower(signal, release: float):
    """Instant-attack / one-pole-release envelope: rises with |x| immediately,
    falls along the Smooth. (A dedicated asymmetric one-pole is a ten-line C
    primitive; built here from Abs/Smooth/If — SYNTHESIS.md finding 6.)"""
    level = sf.Abs(signal)
    released = sf.Smooth(level, release)
    return sf.If(level > released, level, released)


class Console:
    def __init__(self, graph, cfg: ConsoleConfig = ConsoleConfig()) -> None:
        self.graph = graph
        self.cfg = cfg
        trims = dict(cfg.layer_trim)
        eqs = dict(cfg.strip_eq)
        rev_sends = dict(cfg.reverb_layer_send)
        dly_sends = dict(cfg.delay_layer_send)

        self.instruments: dict[str, str] = {}  # layer -> patch, set per bar

        # --- lever-facing controls (Smooth = audio-rate glide on retarget)
        self.cutoff = sf.Smooth(2500.0, 0.9995)
        self.reverb_send = sf.Smooth(0.20, 0.999)
        self.delay_send = sf.Smooth(0.10, 0.999)
        self.drive = sf.Smooth(0.15, 0.999)
        self.width = sf.Smooth(0.70, 0.999)
        self.delay_time = sf.Smooth(0.45, 0.9995)
        self.duck_depth = sf.Smooth(0.0, 0.999)
        self.tension_ctl = sf.Smooth(0.3, 0.999)
        self.energy_ctl = sf.Smooth(0.5, 0.999)
        self.shimmer_gain = sf.Smooth(0.0, 0.999)

        # --- shared voice resources (sampler + wavetable banks, per console)
        self.wavetable_bank = patches.make_wavetable_bank()
        self.bell_sample = patches.make_bell_sample(int(graph.sample_rate))

        # --- mod matrix: shared sources summed per destination; cutoff takes
        # its sum as a ratio, width/shimmer additively (clipped at use sites)
        sources = {
            "lfo_slow": sf.SineOscillator(0.11),
            "lfo_fast": sf.SineOscillator(5.3),
            "drift": sf.Smooth(sf.SampleAndHold(patches._noise(0xD21F7), sf.Impulse(0.4)), 0.9995),
            "tension": self.tension_ctl,
            "energy": self.energy_ctl,
        }
        mod = {"cutoff": 0.0, "width": 0.0, "shimmer": 0.0}
        for source, dest, depth in cfg.mod_matrix:
            if source not in sources or dest not in mod:
                raise ValueError(f"unknown mod route {source!r} -> {dest!r}; "
                                 f"sources {sorted(sources)}, destinations {sorted(mod)}")
            mod[dest] = mod[dest] + sources[source] * depth

        # --- audio-rate sweep: apply_params spawns a fresh one-shot envelope
        # onto this bus on big cutoff rises. One-shot-per-event beats a shared
        # retriggered envelope: overlapping events SUM (a flam pumps deeper)
        # and each envelope is immutable once born, like a voice.
        self.sweep_bus = sf.Bus(1)
        self._sweeps: list[list] = []  # [envelope, bars_left] pending cleanup
        self._last_cutoff: float | None = None
        # every subtractive voice taps this instead of the raw Smooth
        self.cutoff_out = self.cutoff * (1.0 + mod["cutoff"]) \
            * (1.0 + sf.Clip(self.sweep_bus, 0.0, 1.0) * cfg.sweep_depth)
        width_node = sf.Clip(self.width + mod["width"], 0.0, 1.3)
        self._shimmer_mod = mod["shimmer"]

        # --- strips: trim -> 3-band EQ -> (chorus) -> (width) [duck applied later]
        self.strips: dict[str, object] = {}
        strip_outs: dict[str, object] = {}
        for layer in ("pad", "bass", "melody", "arp", "perc"):
            bus = sf.Bus(2)
            self.strips[layer] = bus
            out = bus * trims.get(layer, 0.7)
            if layer in eqs:
                lg, mg, hg, lof, hif = eqs[layer]
                out = sf.EQ(out, lg, mg, hg, lof, hif)
            if layer in cfg.chorus_layers:
                out = self._chorus(out)
            if layer == "pad":
                out = sf.StereoWidth(out, width=width_node)
            strip_outs[layer] = out

        # --- sidechain duck: schedule mode sums fresh one-shot envelopes
        # (spawned per kick by note_on, removed with the kick voice — like
        # the sweep bus, one-shots sum so kick flams pump deeper); detect
        # mode runs an envelope follower on the drum strip instead
        self.duck_bus = sf.Bus(1)
        self._companions: dict[int, list[tuple[object, object]]] = {}  # id(voice) -> [(bus, node)]
        if cfg.sidechain == "detect":
            drums = sf.ChannelMixer(1, strip_outs["perc"])
            env = _follower(drums, cfg.detect_release)
            duck_signal = sf.Clip(env * cfg.detect_sensitivity, 0.0, 1.0)
        else:
            duck_signal = sf.Clip(self.duck_bus, 0.0, 1.0)
        duck_gain = 1.0 - duck_signal * self.duck_depth
        for layer in cfg.duck_layers:
            strip_outs[layer] = strip_outs[layer] * duck_gain

        # --- granular shimmer: grains from the pad's recent past, repitched
        # up, random position/pan per grain, density riding tension
        history = sf.Buffer(1, int(cfg.shimmer_history_seconds * graph.sample_rate))
        writer = sf.HistoryBufferWriter(history, sf.ChannelMixer(1, strip_outs["pad"]))
        graph.add_node(writer)  # sink: pull explicitly
        self.shimmer_density = sf.Smooth(3.0, 0.999)
        grain_clock = sf.RandomImpulse(self.shimmer_density)
        grain_clock.set_seed(0x5EED)  # stochastic nodes seed from global entropy otherwise
        grains = sf.Granulator(
            history,
            clock=grain_clock,
            pos=(patches._noise(0x905) * 0.5 + 0.5) * (cfg.shimmer_history_seconds - 0.2),
            duration=cfg.shimmer_grain_duration,
            pan=patches._noise(0x9A4),
            rate=cfg.shimmer_grain_rate,
        )
        shimmer = grains * sf.Clip(self.shimmer_gain + self._shimmer_mod, 0.0, 1.0)

        dry = self.dry = sum(strip_outs.values()) + shimmer * 0.2

        # --- reverb bus: predelay + input diffusion -> 4-line Householder FDN
        rev_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = rev_sends.get(layer, 0.0)
            if send > 0.0:
                rev_in.add_input(out * send * self.reverb_send)
        rev_in.add_input(shimmer)  # shimmer blooms through the wash
        mono = sf.ChannelMixer(1, rev_in)
        pre = sf.OneTapDelay(mono, cfg.reverb_predelay, max_delay_time=0.2)
        diffused = sf.AllpassDelay(sf.AllpassDelay(pre, 0.005, 0.5, 0.02), 0.0017, 0.5, 0.01)
        reverb_out = self.reverb_out = self._fdn(diffused)

        # --- delay bus: tempo-synced ping-pong (alternating L/R bounces)
        dly_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = dly_sends.get(layer, 0.0)
            if send > 0.0:
                dly_in.add_input(out * send * self.delay_send)
        delay_out = self.delay_out = self._pingpong(sf.ChannelMixer(1, dly_in)) * 0.7

        # --- master: drive -> glue compression -> lookahead limiter -> guard
        pre_master = dry + reverb_out + delay_out
        # gain staging: tanh saturates toward +-1.0, so pull the driven
        # signal down before dynamics or the limiter lives at the ceiling
        driven = sf.Tanh(pre_master * (1.0 + self.drive * 4.0)) * 0.7
        glued = sf.Compressor(driven, threshold=0.30, ratio=2.5,
                              attack_time=0.012, release_time=0.18)
        # NOTE: signalflow's Maximiser is a loudness maximizer whose auto
        # makeup gain overshoots wildly here (measured 34x) — loudness comes
        # from fixed makeup, and the ceiling from our lookahead limiter.
        loud = sf.Tanh(glued * cfg.master_makeup)
        limited = self._limiter(sf.DCFilter(loud))
        self.master = sf.Clip(limited, -0.95, 0.95)
        graph.play(self.master)

    # --- processor builders ----------------------------------------------------

    def _chorus(self, signal):
        """Stereo bus chorus: two taps modulated at decorrelated rates."""
        cfg = self.cfg
        mono = sf.ChannelMixer(1, signal)
        max_t = cfg.chorus_base + cfg.chorus_depth + 0.005
        taps = [
            sf.OneTapDelay(mono, cfg.chorus_base + sf.SineOscillator(rate) * cfg.chorus_depth, max_t)
            for rate in cfg.chorus_rates
        ]
        wet = sf.StereoPanner(taps[0], -0.7) + sf.StereoPanner(taps[1], 0.7)
        return signal * (1.0 - cfg.chorus_mix) + wet * cfg.chorus_mix

    def _fdn(self, mono_in):
        """4-line feedback delay network, Householder matrix (y_i = x_i - Σx/2),
        per-line lowpass damping inside the loop, per-line gain calibrated so
        every line decays to -60 dB in fdn_t60 seconds."""
        cfg = self.cfg
        sr = self.graph.sample_rate
        block = self.graph.output_buffer_size
        if min(cfg.fdn_delays) * sr < block:
            raise ValueError(
                f"FDN line delays ({min(cfg.fdn_delays) * 1000:.1f} ms min) must exceed "
                f"one hardware block ({block / sr * 1000:.1f} ms) — signalflow's feedback "
                f"loop minimum. Raise fdn_delays or lower the device buffer size.")
        buffers = [sf.Buffer(1, int(0.5 * sr)) for _ in cfg.fdn_delays]
        # Read side: a looped BufferPlayer at rate 1, NOT FeedbackBufferReader —
        # the reader's phase member is uninitialized upstream (found via
        # valgrind after a long nondeterminism hunt, SYNTHESIS.md finding 8),
        # so its loop delay depends on stale heap contents. The player has the
        # same read-the-ring semantics with a properly initialized phase.
        damped = [
            sf.SVFilter(sf.BufferPlayer(buf, rate=1.0, loop=True), "low_pass",
                        cutoff=cfg.fdn_damping_hz, resonance=0.0)
            for buf in buffers
        ]
        total = sum(damped)
        inject = mono_in * (1.0 / len(buffers))
        for buf, line, delay in zip(buffers, damped, cfg.fdn_delays):
            gain = 10.0 ** (-3.0 * delay / cfg.fdn_t60)
            writer = sf.FeedbackBufferWriter(buf, inject + (line - 0.5 * total) * gain, delay)
            self.graph.add_node(writer)  # writers are sinks; pull them explicitly
        left = damped[0] + damped[2] * 0.7
        right = damped[1] + damped[3] * 0.7
        stereo = sf.StereoPanner(left, -1.0) + sf.StereoPanner(right, 1.0)
        return sf.BiquadFilter(stereo, "high_shelf", cfg.reverb_shelf_hz, 0.707,
                               cfg.reverb_shelf_db)

    def _pingpong(self, mono):
        """Alternating-side echoes from feedforward taps over one feedback comb:
        ping = x + comb(x, 2d)·f², then L taps at d (gains 1, f², ...) and R at
        2d (gains f, f³, ...) — no cross-channel feedback loop required."""
        f = self.cfg.delay_feedback
        d, max_t = self.delay_time, self.cfg.delay_max_seconds
        ping = mono + sf.CombDelay(mono, d * 2.0, feedback=f * f, max_delay_time=max_t) * (f * f)
        left = sf.OneTapDelay(ping, d, max_t)
        right = sf.OneTapDelay(ping, d * 2.0, max_t) * f
        return sf.StereoPanner(left, -0.8) + sf.StereoPanner(right, 0.8)

    def _limiter(self, signal):
        """Lookahead limiter. The detector is a sliding-window MAX over the
        lookahead span (the undelayed level plus delayed copies, folded with
        If) — a plain follower cannot hold a peak without self-feedback
        (env = max(|x|, a*env) is a ten-line C primitive; stock nodes lack
        it, SYNTHESIS.md finding 6). Holding the peak for the full window
        keeps the gain converged when the delayed peak reaches the
        multiplier. Channels limit independently (unlinked); a linked
        limiter needs a cross-channel max — another C-library requirement."""
        cfg = self.cfg
        la = cfg.limiter_lookahead
        sr = self.graph.sample_rate
        # gapless sliding-window max by doubling: after stage k the signal is
        # the max over the last 2^k samples — max(w_n(t), w_n(t - n)) covers 2n
        window = sf.Abs(signal)
        span = 1
        while span < la * sr:
            tap = sf.OneTapDelay(window, span / sr, span / sr + 0.001)
            window = sf.If(window > tap, window, tap)
            span *= 2
        released = sf.Smooth(window, cfg.limiter_release)
        env = sf.If(window > released, window, released)
        over = sf.If(env > cfg.limiter_ceiling, env, cfg.limiter_ceiling)
        gain = sf.Smooth(cfg.limiter_ceiling / over, cfg.limiter_gain_smooth)
        delayed = sf.OneTapDelay(signal, la, la + 0.01)
        return delayed * gain

    # --- event-side API -------------------------------------------------------

    def note_on(self, event: NoteEvent, dur_seconds: float) -> tuple[str, object, float]:
        """Build and attach a voice (variant per the current instruments map).
        Returns (layer, node, total_seconds); the caller owns detaching it
        after total_seconds (explicit voice lifecycle, like a C allocator)."""
        amp = (event.velocity / 127.0) ** self.cfg.velocity_curve
        patch = self.instruments.get(event.layer, "")
        if event.layer == "perc":
            node, total = patches.drum_voice(event.pitch, amp)
            if event.pitch == 36 and self.cfg.sidechain != "detect":
                # kick pumps the duck bus: a fresh one-shot envelope, removed
                # along with the kick voice (companion lifecycle)
                duck = sf.ASREnvelope(0.001, 0.02, 0.28, curve=2.0)
                self.duck_bus.add_input(duck)
                self._companions.setdefault(id(node), []).append((self.duck_bus, duck))
        elif event.layer == "pad":
            if patch == "morph":
                node, total = patches.wavetable_pad_voice(
                    _hz(event.pitch), amp, dur_seconds, self.cutoff_out * 0.8, self.wavetable_bank)
            else:
                node, total = patches.pad_voice(_hz(event.pitch), amp, dur_seconds,
                                                self.cutoff_out * 0.8, variant=patch or "warm")
        elif event.layer == "bass":
            node, total = patches.bass_voice(_hz(event.pitch), amp, dur_seconds,
                                             self.cutoff_out * 0.6 + 120.0, variant=patch or "round")
        elif event.layer == "melody":
            if patch == "keys":
                node, total = patches.sampler_voice(
                    event.pitch, amp, dur_seconds, self.cutoff_out,
                    self.bell_sample, int(self.graph.sample_rate))
            else:
                node, total = patches.lead_voice(_hz(event.pitch), amp, dur_seconds,
                                                 self.cutoff_out, variant=patch or "soft")
        else:
            node, total = patches.arp_voice(_hz(event.pitch), amp, dur_seconds,
                                            variant=patch or "pluck")
        self.strips[event.layer].add_input(node)
        return event.layer, node, total

    def remove(self, layer: str, node) -> None:
        for bus, companion in self._companions.pop(id(node), ()):
            try:
                bus.remove_input(companion)
            except Exception:
                pass
        try:
            self.strips[layer].remove_input(node)
        except Exception:
            pass  # already detached

    # --- lever-side API -------------------------------------------------------

    def apply_params(self, params, affect, bpm: float, bar_seconds: float | None = None) -> None:
        """Retarget the Smooth controls from the bar's mapped parameters.
        Instrument swaps take effect on the next note_on — sounding voices
        keep their patch (a voice is immutable once allocated). A big upward
        cutoff retarget additionally triggers the sweep envelope, shaped over
        one bar (audio-rate automation vs. the one-pole's fixed glide)."""
        _, energy, tension = affect
        self.instruments = dict(params.instruments)
        cutoff = max(120.0, params.filter_cutoff)
        for entry in self._sweeps:  # age out finished sweep envelopes
            entry[1] -= 1
        for env, _ in (e for e in self._sweeps if e[1] <= 0):
            try:
                self.sweep_bus.remove_input(env)
            except Exception:
                pass
        self._sweeps = [e for e in self._sweeps if e[1] > 0]
        if (bar_seconds and self._last_cutoff is not None
                and cutoff > self._last_cutoff * self.cfg.sweep_trigger_ratio
                and self.cfg.sweep_depth > 0.0):
            env = sf.ASREnvelope(bar_seconds * 0.9, 0.0, bar_seconds * 1.5, curve=1.5)
            self.sweep_bus.add_input(env)
            self._sweeps.append([env, 6])  # outlives attack+release at any tempo
        self._last_cutoff = cutoff
        self.cutoff.set_input("input", cutoff)
        self.reverb_send.set_input("input", params.reverb_send)
        self.delay_send.set_input("input", params.delay_send)
        self.drive.set_input("input", params.drive)
        self.width.set_input("input", params.stereo_width)
        self.duck_depth.set_input("input", 0.4 * energy * energy)
        self.tension_ctl.set_input("input", tension)
        self.energy_ctl.set_input("input", energy)
        self.shimmer_gain.set_input("input", self.cfg.shimmer_max * tension * tension)
        self.shimmer_density.set_input("input", 2.0 + tension * 14.0)
        dotted_eighth = 0.75 * 60.0 / max(bpm, 30.0)
        self.delay_time.set_input("input", min(dotted_eighth, (self.cfg.delay_max_seconds - 0.1) / 2.0))
