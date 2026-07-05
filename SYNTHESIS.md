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

| Layer | Design (calm tier → hot tier, energy-swapped) |
|---|---|
| pad | 3 detuned saws (±0.4%) → shared-cutoff lowpass → slow ASR; strip StereoWidth. **bright**: ±0.9% spread, cutoff ×1.7, resonance up, fast bloom |
| bass | saw + sub-octave sine → lowpass with plucky filter envelope. **driven**: tanh pre-drive, deeper/hotter sweep |
| melody | triangle/saw blend, delayed vibrato (LFO depth ramped by a Line) → lowpass. **hard**: saw/square stack, earlier+deeper vibrato, snappy attack |
| arp | 2-op FM pluck: 3:1 ratio, index on a fast-decay envelope. **glass**: inharmonic 7:1, hotter index, longer shimmer |
| kick | sine with pitch-drop envelope (129→44 Hz) + band-passed noise click |
| snare | band-passed noise rattle + 195 Hz tonal body, separate decays |
| hats/shaker/crash | filtered noise families: HP short/long, BP resonant, shimmer layer |
| toms | pitch-dropping sines + noise transient, three tunings |

Velocity maps to amplitude through a ^1.5 curve; bass/pad/melody share
lever-driven cutoff Smooths (scaled per layer), so one retarget sweeps every
sounding voice — node fanout, not per-voice bookkeeping. Cutoff also
**keytracks** per voice (a scalar factor `(f/261.63)^kt` baked in at
allocation — pitch is known then, so tracking costs nothing at render time).

## Console topology (v2 as of M10)

- **Strips** per layer: gain trim → **3-band channel EQ** (bass owns the
  lows, pad clears mud, melody/arp get presence and air, perc keeps thump
  and snap) → (pad) **bus chorus** (two taps modulated at 0.6/0.73 Hz,
  panned wide, 35% mix) → (pad) StereoWidth → duck gain (pad, arp).
- **Reverb bus**: per-layer send gains × global send Smooth → mono sum →
  20 ms predelay → 2 input-diffusion allpasses → hand-rolled **4-line FDN**
  (Householder matrix `y_i = x_i − Σx/2`; inharmonic delays 33.7/45.3/57.7/
  68.9 ms; **lowpass damping inside the loop** — the thing Schroeder combs
  couldn't express with stock nodes; per-line gain `10^(−3d/T60)` for a
  uniform T60 = 2.2 s) → high-shelf tone (−4 dB @ 4.5 kHz). Built on
  signalflow's feedback buffer pair — see finding 5 for the constraint.
- **Delay bus**: **tempo-synced ping-pong** — feedforward taps over one
  feedback comb (`ping = x + comb(x, 2d)·f²`, L taps at d, R at 2d·f) give
  alternating-side echoes without a cross-channel feedback loop.
- **Ducking**: schedule-driven sidechain by default — every kick retriggers
  a shared ASR envelope that dips pad/arp strips (depth ← energy²); the
  symbolic layer already knows what a detector would rediscover.
  `sidechain="detect"` switches to an envelope follower on the drum strip —
  the technique needed when the trigger source is unscheduled audio.
- **Master**: soft saturation `tanh(x·(1+4·drive))` with post-scale →
  glue compressor (thr .30, ratio 2.5:1, 12/180 ms) → fixed makeup into a
  tanh knee → DC blocker → **lookahead limiter** (5 ms, ceiling 0.92,
  sliding-window-max detector — finding 6) → hard clip guard at ±0.95.
- **Export**: deterministic **TPDF dither** at ±1 LSB, added only at the
  final 16-bit quantization, never while the signal stays float.

## Lever → DSP mapping (extends control/mapping.py)

| Parameter | Driven by | Shape |
|---|---|---|
| `filter_cutoff` | energy (4.2 octaves), +valence tint | 350 Hz → ~6.4 kHz, exponential |
| `reverb_send` | tension ↑ and stillness (1−energy) ↑ | tense OR calm = wetter |
| `delay_send` | tension × energy | active suspense echoes |
| `drive` | energy² | saturation blooms late |
| `stereo_width` | valence | dark = narrow, bright = wide |
| duck depth | energy² | pumping appears with intensity |
| `instruments` | energy tiers | phrase-quantized patch swaps (voice presets, finding 4) |

Two smoothing tiers, deliberately: the **mapper** slews musically (per bar,
boundary-quantized); the **console** glides at audio rate (one-pole Smooth,
~20–45 ms) so retargets never zipper. The C library needs the second tier;
the engine's conductor port provides the first.

## What the C library therefore needs

Primitives: band-limited saw/square/triangle/sine, white noise, wavetable
(future); ASR/ADSR envelopes with curve shaping **and retrigger**; one-pole
smoothing on every audible parameter; SVF (LP/HP/BP + resonance); biquads
with **peak and shelf types** (dB gains) and a cheap 3-band channel EQ; comb
and allpass delays with runtime-variable delay time (chorus = a modulated
tap); a **feedback loop primitive** (write/read pair or single-sample loops
— finding 5); **asymmetric one-pole followers and a sliding-window max**
(finding 6), channel-linked detector option; DC blocker; stereo pan and
mid/side width; tanh saturator; hard clip; feedback compressor with
**specified, bounded makeup behavior** (see findings); TPDF dither at the
final quantization; mono summing; buses with dynamic voice attach/detach.

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
4. **Instrument swaps are presets, not new DSP.** Every energy-tier variant
   (M9) is the same voice topology with different constants — detune spread,
   envelope times, filter scaling, FM ratio. A sounding voice keeps its patch;
   the swap applies from the next allocation, boundary-quantized upstream.
   For the C library: voices need a preset/parameter-block concept resolved
   at allocation time — no live-patching of a voice's topology, no per-voice
   branching in the render loop.
5. **Feedback loops have a one-block minimum in block-based graphs.**
   signalflow's feedback buffer pair makes the FDN possible (in-loop damping,
   arbitrary matrices) but rejects loop delays shorter than one hardware
   block — fine for reverb lines (>30 ms), prohibitive for flangers (<10 ms)
   and impossible for one-sample recursions. The console now refuses to
   build an FDN that violates it, with the device buffer in the message.
   For the C library: feedback is a first-class need at THREE granularities —
   sample (filters, followers), short-loop (flanger/comb), and block (FDN).
6. **Peak detectors need self-feedback; graph-pure workarounds exist but
   teach the requirement.** A "follower" built from Abs + symmetric Smooth +
   If tracks averages, not peaks — the first limiter leaked 1.4% of samples
   into the clip guard because its envelope forgot each peak within samples.
   The fix is a gapless **sliding-window max by doubling** (max(w, w@2^k)
   cascades, O(log n) nodes) spanning the lookahead, but the real lesson is
   the missing ten-line primitive `env = max(|x|, a·env)`. Related: one-pole
   gain smoothing never fully converges inside the lookahead (we tolerate
   ~1% of a step); a linear attack ramp hits the target exactly. And RMS
   that reports once per block quantizes detector timing to the block.

## Roadmap (authored-production techniques not yet exercised)

Sampler/wavetable layers and hybrid (synth + recorded) instruments ·
granular textures · a general mod matrix · audio-rate automation curves ·
convolution reverb · flanger/phaser (blocked in signalflow by the one-block
feedback minimum, finding 5 — a native C short-loop primitive unblocks them).
