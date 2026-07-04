# SYNTHESIS.md — the signalflow backend as a requirements probe

The `musicgen/synth/` package replaces the General-MIDI ceiling with in-process
DSP (signalflow). Its purpose is dual: better sound now, and a concrete,
tested inventory of **what the Anoptic engine's in-house C audio library must
provide**. Everything below was needed to make ~3 minutes of lever-driven
music sound intentional; nothing is speculative.

## Architecture

```
BarResult stream (same IR the MIDI path consumes)
      │  events (beats) ── BeatClock/tempo map ──► seconds ──► frames
      ▼
scheduler        offline: exact chunked rendering — the graph is stepped in
(render.py)      sub-blocks that stop at every note-on, parameter retarget,
      │          and voice removal (sample-accurate event boundaries)
      │          realtime: one-bar look-ahead against the monotonic clock
      ▼
console          per-layer strips ─► send buses ─► master
(console.py)     all lever-facing values land on one-pole Smooth nodes
      ▼
voices           plain node chains with EXPLICIT lifecycle: the scheduler
(patches.py)     attaches a voice to its strip and detaches it at a known
                 end time — no garbage-collected voices, like a C allocator
```

## Voice inventory (techniques exercised)

| Layer | Design |
|---|---|
| pad | 3 detuned saws (unison ±0.4%) → shared-cutoff lowpass → slow ASR; strip-level StereoWidth |
| bass | saw + sub-octave sine → lowpass with plucky filter envelope (cutoff × env) |
| melody | triangle/saw blend, delayed vibrato (LFO depth ramped by a Line) → lowpass |
| arp | 2-op FM pluck: 3:1 ratio, modulation index on a fast-decay envelope |
| kick | sine with pitch-drop envelope (129→44 Hz) + band-passed noise click |
| snare | band-passed noise rattle + 195 Hz tonal body, separate decays |
| hats/shaker/crash | filtered noise families: HP short/long, BP resonant, shimmer layer |
| toms | pitch-dropping sines + noise transient, three tunings |

Velocity maps to amplitude through a ^1.5 curve; bass/pad/melody share
lever-driven cutoff Smooths (scaled per layer), so one retarget sweeps every
sounding voice — node fanout, not per-voice bookkeeping.

## Console topology

- **Strips** per layer: gain trim → (pad only) StereoWidth → duck gain (pad, arp).
- **Reverb bus**: per-layer send gains × global send Smooth → mono sum →
  20 ms predelay → hand-rolled **Schroeder reverb** (4 parallel combs
  29.7/37.1/41.1/43.7 ms, fb .77–.71 → 2 series allpasses) → lowpass tone.
  signalflow ships no reverb node; the C library won't either — this is the
  algorithm to port (or upgrade to FDN).
- **Delay bus**: sends → feedback comb, **delay time tempo-synced** to a
  dotted 8th (retargeted per bar from the live BPM).
- **Ducking**: schedule-driven sidechain — every kick retriggers a shared
  ASR envelope that dips pad/arp strip gains (depth ← energy²). The symbolic
  layer already knows what an audio detector would have to rediscover.
- **Master**: soft saturation `tanh(x·(1+4·drive))` with post-scale →
  glue compressor (thr .30, ratio 2.5:1, 12/180 ms) → fixed makeup into a
  tanh knee → hard clip guard at ±0.95.

## Lever → DSP mapping (extends control/mapping.py)

| Parameter | Driven by | Shape |
|---|---|---|
| `filter_cutoff` | energy (4.2 octaves), +valence tint | 350 Hz → ~6.4 kHz, exponential |
| `reverb_send` | tension ↑ and stillness (1−energy) ↑ | tense OR calm = wetter |
| `delay_send` | tension × energy | active suspense echoes |
| `drive` | energy² | saturation blooms late |
| `stereo_width` | valence | dark = narrow, bright = wide |
| duck depth | energy² | pumping appears with intensity |

Two smoothing tiers, deliberately: the **mapper** slews musically (per bar,
boundary-quantized); the **console** glides at audio rate (one-pole Smooth,
~20–45 ms) so retargets never zipper. The C library needs the second tier;
the engine's conductor port provides the first.

## What the C library therefore needs

Primitives: band-limited saw/square/triangle/sine, white noise, wavetable
(future); ASR/ADSR envelopes with curve shaping **and retrigger**; one-pole
smoothing on every audible parameter; SVF (LP/HP/BP + resonance); comb and
allpass delays with runtime-variable delay time; stereo pan and mid/side
width; tanh saturator; hard clip; feedback compressor with **specified,
bounded makeup behavior** (see findings); mono summing; buses with dynamic
voice attach/detach.

Semantics: DAG with node fanout (shared control nodes feeding many voices);
block rendering that can **split blocks at arbitrary sample offsets** for
event accuracy; voice lifecycle owned by the scheduler, not a collector;
headless faster-than-realtime rendering and realtime output through the same
graph; device/render block sizes decoupled and explicit.

## Findings the hard way (each cost a debugging session)

1. **Dynamics processors must document their makeup gain.** signalflow's
   `Maximiser` is a loudness maximizer; in this chain its auto-makeup
   overshot to 34× and pinned 27% of samples at full scale. Replaced with
   fixed makeup + tanh knee + clip guard. For the C library: no implicit
   gain, ever.
2. **Async file recording drops samples when rendering faster than
   realtime.** Capture offline renders synchronously in-graph
   (`BufferRecorder` into a preallocated buffer), never through the
   realtime-oriented recorder.
3. **Realtime diagnostics don't apply offline.** signalflow prints
   "buffer overrun?" whenever a block's compute time exceeds its realtime
   duration (graph.cpp: cpu_usage > 1.0) — correct for a live device,
   meaningless when deliberately rendering faster than realtime (dense bars
   trip it constantly while the whole render finishes 10x faster than the
   piece). For the C library: separate "deadline missed" reporting from
   headless rendering, and expose per-block CPU stats instead of printing.

## Roadmap (authored-production techniques not yet exercised)

Per-strip EQ · audio-detected sidechain compression (vs. the schedule-driven
duck) · chorus/flanger/phaser · ping-pong delay · FDN or convolution reverb ·
sampler/wavetable layers and hybrid (synth + recorded) instruments ·
granular textures · lookahead limiting · per-voice keytracking and a general
mod matrix · audio-rate automation curves · stereo unison voice spreading ·
dither on export.
