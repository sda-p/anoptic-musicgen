"""The mixing console: per-layer strips, send buses, hand-rolled Schroeder
reverb, tempo-synced feedback delay, and a master chain (drive -> glue
compressor -> limiter). Lever-mapped DSP parameters land on Smooth nodes, so
one retarget glides every dependent voice and bus (SYNTHESIS.md).

Sidechain-style pumping is schedule-driven rather than detected: the renderer
tells the console when a kick fires and a retriggerable envelope ducks the
pad/arp strips — the symbolic layer already knows what a detector would
have to rediscover from audio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    reverb_layer_send: tuple[tuple[str, float], ...] = (
        ("pad", 1.00), ("bass", 0.10), ("melody", 0.75), ("arp", 0.90), ("perc", 0.30),
    )
    delay_layer_send: tuple[tuple[str, float], ...] = (
        ("pad", 0.00), ("bass", 0.00), ("melody", 1.00), ("arp", 0.80), ("perc", 0.00),
    )
    duck_layers: tuple[str, ...] = ("pad", "arp")
    velocity_curve: float = 1.5
    # Schroeder reverb constants (comb delay seconds, feedback)
    reverb_combs: tuple[tuple[float, float], ...] = (
        (0.0297, 0.77), (0.0371, 0.75), (0.0411, 0.73), (0.0437, 0.71),
    )
    reverb_predelay: float = 0.02
    reverb_tone_hz: float = 4500.0
    delay_feedback: float = 0.42
    delay_max_seconds: float = 1.5
    master_makeup: float = 1.5


class Console:
    def __init__(self, graph, cfg: ConsoleConfig = ConsoleConfig()) -> None:
        self.graph = graph
        self.cfg = cfg
        trims = dict(cfg.layer_trim)
        rev_sends = dict(cfg.reverb_layer_send)
        dly_sends = dict(cfg.delay_layer_send)

        # --- lever-facing controls (Smooth = audio-rate glide on retarget)
        self.cutoff = sf.Smooth(2500.0, 0.9995)
        self.reverb_send = sf.Smooth(0.20, 0.999)
        self.delay_send = sf.Smooth(0.10, 0.999)
        self.drive = sf.Smooth(0.15, 0.999)
        self.width = sf.Smooth(0.70, 0.999)
        self.delay_time = sf.Smooth(0.45, 0.9995)
        self.duck_depth = sf.Smooth(0.0, 0.999)

        # --- sidechain-style duck: retriggered per kick by the renderer
        self.duck_env = sf.ASREnvelope(0.001, 0.02, 0.28, curve=2.0)
        duck_gain = 1.0 - self.duck_env * self.duck_depth

        # --- strips
        self.strips: dict[str, object] = {}
        strip_outs: dict[str, object] = {}
        for layer in ("pad", "bass", "melody", "arp", "perc"):
            bus = sf.Bus(2)
            self.strips[layer] = bus
            out = bus * trims.get(layer, 0.7)
            if layer == "pad":
                out = sf.StereoWidth(out, width=self.width)
            if layer in cfg.duck_layers:
                out = out * duck_gain
            strip_outs[layer] = out

        dry = sum(strip_outs.values()) * 1.0

        # --- reverb bus (hand-rolled Schroeder: parallel combs -> allpasses)
        rev_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = rev_sends.get(layer, 0.0)
            if send > 0.0:
                rev_in.add_input(out * send * self.reverb_send)
        mono = sf.ChannelMixer(1, rev_in)
        pre = sf.OneTapDelay(mono, cfg.reverb_predelay, max_delay_time=0.2)
        combs = sum(
            sf.CombDelay(pre, t, feedback=fb, max_delay_time=0.2)
            for t, fb in cfg.reverb_combs
        ) * (1.0 / len(cfg.reverb_combs))
        diffused = sf.AllpassDelay(sf.AllpassDelay(combs, 0.005, 0.5, 0.02), 0.0017, 0.5, 0.01)
        reverb_out = sf.StereoPanner(
            sf.SVFilter(diffused, "low_pass", cutoff=cfg.reverb_tone_hz, resonance=0.0), 0.0
        )

        # --- delay bus (tempo-synced feedback delay; time set per bar)
        dly_in = sf.Bus(2)
        for layer, out in strip_outs.items():
            send = dly_sends.get(layer, 0.0)
            if send > 0.0:
                dly_in.add_input(out * send * self.delay_send)
        delay_out = sf.CombDelay(
            dly_in, self.delay_time, feedback=cfg.delay_feedback,
            max_delay_time=cfg.delay_max_seconds,
        ) * 0.7

        # --- master: drive -> glue compression -> limiter
        pre_master = dry + reverb_out + delay_out
        # gain staging: tanh saturates toward +-1.0, so pull the driven
        # signal down before dynamics or the limiter lives at the ceiling
        driven = sf.Tanh(pre_master * (1.0 + self.drive * 4.0)) * 0.7
        glued = sf.Compressor(driven, threshold=0.30, ratio=2.5,
                              attack_time=0.012, release_time=0.18)
        # NOTE: signalflow's Maximiser is a loudness maximizer whose auto
        # makeup gain overshoots wildly here (measured 34x) — final stage is
        # fixed makeup into a soft tanh knee, with a hard clip as the guard.
        loud = sf.Tanh(glued * cfg.master_makeup)
        self.master = sf.Clip(loud, -0.95, 0.95)
        graph.play(self.master)

    # --- event-side API -------------------------------------------------------

    def note_on(self, event: NoteEvent, dur_seconds: float) -> tuple[str, object, float]:
        """Build and attach a voice. Returns (layer, node, total_seconds);
        the caller owns detaching it after total_seconds (explicit voice
        lifecycle, like a C voice allocator)."""
        amp = (event.velocity / 127.0) ** self.cfg.velocity_curve
        if event.layer == "perc":
            node, total = patches.drum_voice(event.pitch, amp)
            if event.pitch == 36:  # kick pumps the duck bus
                self.duck_env.trigger()
        elif event.layer == "pad":
            node, total = patches.pad_voice(_hz(event.pitch), amp, dur_seconds, self.cutoff * 0.8)
        elif event.layer == "bass":
            node, total = patches.bass_voice(_hz(event.pitch), amp, dur_seconds, self.cutoff * 0.6 + 120.0)
        elif event.layer == "melody":
            node, total = patches.lead_voice(_hz(event.pitch), amp, dur_seconds, self.cutoff)
        else:
            node, total = patches.arp_voice(_hz(event.pitch), amp, dur_seconds)
        self.strips[event.layer].add_input(node)
        return event.layer, node, total

    def remove(self, layer: str, node) -> None:
        try:
            self.strips[layer].remove_input(node)
        except Exception:
            pass  # already detached

    # --- lever-side API -------------------------------------------------------

    def apply_params(self, params, affect, bpm: float) -> None:
        """Retarget the Smooth controls from the bar's mapped parameters."""
        _, energy, _ = affect
        self.cutoff.set_input("input", max(120.0, params.filter_cutoff))
        self.reverb_send.set_input("input", params.reverb_send)
        self.delay_send.set_input("input", params.delay_send)
        self.drive.set_input("input", params.drive)
        self.width.set_input("input", params.stereo_width)
        self.duck_depth.set_input("input", 0.4 * energy * energy)
        dotted_eighth = 0.75 * 60.0 / max(bpm, 30.0)
        self.delay_time.set_input("input", min(dotted_eighth, self.cfg.delay_max_seconds - 0.05))
