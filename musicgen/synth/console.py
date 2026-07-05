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
                out = sf.StereoWidth(out, width=self.width)
            strip_outs[layer] = out

        # --- sidechain duck: a retriggered envelope (schedule mode, fed by
        # note_on) or an envelope follower on the drum strip (detect mode)
        self.duck_env = sf.ASREnvelope(0.001, 0.02, 0.28, curve=2.0)
        if cfg.sidechain == "detect":
            drums = sf.ChannelMixer(1, strip_outs["perc"])
            env = _follower(drums, cfg.detect_release)
            duck_signal = sf.Clip(env * cfg.detect_sensitivity, 0.0, 1.0)
        else:
            duck_signal = self.duck_env
        duck_gain = 1.0 - duck_signal * self.duck_depth
        for layer in cfg.duck_layers:
            strip_outs[layer] = strip_outs[layer] * duck_gain

        dry = sum(strip_outs.values()) * 1.0

        # --- reverb bus: predelay + input diffusion -> 4-line Householder FDN
        rev_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = rev_sends.get(layer, 0.0)
            if send > 0.0:
                rev_in.add_input(out * send * self.reverb_send)
        mono = sf.ChannelMixer(1, rev_in)
        pre = sf.OneTapDelay(mono, cfg.reverb_predelay, max_delay_time=0.2)
        diffused = sf.AllpassDelay(sf.AllpassDelay(pre, 0.005, 0.5, 0.02), 0.0017, 0.5, 0.01)
        reverb_out = self._fdn(diffused)

        # --- delay bus: tempo-synced ping-pong (alternating L/R bounces)
        dly_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = dly_sends.get(layer, 0.0)
            if send > 0.0:
                dly_in.add_input(out * send * self.delay_send)
        delay_out = self._pingpong(sf.ChannelMixer(1, dly_in)) * 0.7

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
        damped = [
            sf.SVFilter(sf.FeedbackBufferReader(buf), "low_pass",
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
            if event.pitch == 36:  # kick pumps the duck bus (schedule mode)
                self.duck_env.trigger()
        elif event.layer == "pad":
            node, total = patches.pad_voice(_hz(event.pitch), amp, dur_seconds,
                                            self.cutoff * 0.8, variant=patch or "warm")
        elif event.layer == "bass":
            node, total = patches.bass_voice(_hz(event.pitch), amp, dur_seconds,
                                             self.cutoff * 0.6 + 120.0, variant=patch or "round")
        elif event.layer == "melody":
            node, total = patches.lead_voice(_hz(event.pitch), amp, dur_seconds,
                                             self.cutoff, variant=patch or "soft")
        else:
            node, total = patches.arp_voice(_hz(event.pitch), amp, dur_seconds,
                                            variant=patch or "pluck")
        self.strips[event.layer].add_input(node)
        return event.layer, node, total

    def remove(self, layer: str, node) -> None:
        try:
            self.strips[layer].remove_input(node)
        except Exception:
            pass  # already detached

    # --- lever-side API -------------------------------------------------------

    def apply_params(self, params, affect, bpm: float) -> None:
        """Retarget the Smooth controls from the bar's mapped parameters.
        Instrument swaps take effect on the next note_on — sounding voices
        keep their patch (a voice is immutable once allocated)."""
        _, energy, _ = affect
        self.instruments = dict(params.instruments)
        self.cutoff.set_input("input", max(120.0, params.filter_cutoff))
        self.reverb_send.set_input("input", params.reverb_send)
        self.delay_send.set_input("input", params.delay_send)
        self.drive.set_input("input", params.drive)
        self.width.set_input("input", params.stereo_width)
        self.duck_depth.set_input("input", 0.4 * energy * energy)
        dotted_eighth = 0.75 * 60.0 / max(bpm, 30.0)
        self.delay_time.set_input("input", min(dotted_eighth, (self.cfg.delay_max_seconds - 0.1) / 2.0))
