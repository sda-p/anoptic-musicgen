# anoptic-musicgen

A prototype procedural music system built to inform the audio architecture of
the Anoptic game engine. It generates coherent tonal music from formal music
theory — no ML, no pre-composed material — and steers it in real time through
three semantic levers: **valence** (dark ↔ bright), **energy** (calm ↔
intense), and **tension** (resolved ↔ suspended). Output is MIDI, chosen
because it can be read as text and checked against theory.

The design bias throughout is **inspectability**: every render emits an
annotated per-bar text dump (chords as roman numerals, scale degrees, note
roles), a decision trace ("why did it play that?"), and passes an automated
theory linter. Generation is deterministic per `(seed, bar)`, so A/B
comparisons isolate exactly what a lever changed.

## How it works

```
game / script / keyboard        set_affect(valence, energy, tension)
        │                       set_override("tempo_bpm", 96)
        │                       request_key("Eb")
        ▼
mapping table   affect → tempo, mode (Lydian..Phrygian), density, roughness,
(control/)      articulation, dynamics, register, layer gates, instrument
        │       tiers (energy re-orchestrates timbre), dissonance budget,
        │       cadence policy — every constant in one dataclass
        ▼
conductor       pull-based: advance_bar() → one bar of theory-annotated
(gen/)          events. Functional harmony walk (T→PD→D) with cadence slots,
        │       voice-led pad, bass with approach tones, motif-based melody,
        │       Euclidean percussion with phrase-end fills, arpeggios.
        ▼
modifiers       per-layer chains: strum, humanize, articulate, accent,
        │       echo, swing — pre-modifier IR is preserved for linting
        ▼
outputs         .mid (with tempo map) → FluidSynth .wav │ text dump │ trace
                │ theory linter (verify.py), or a live MIDI port
```

Control changes quantize to musical boundaries: tempo slews per beat,
density/layers change at barlines, mode and cadence policy at phrase
boundaries (`urgent=True` demotes that to the next bar). Chords are generated
one bar ahead so generators can see what is coming.

Key changes are real modulations, not transpositions: `request_key("Eb")`
rides the next phrase cadence through a pivot chord — a chord diatonic in
both keys, then the new key's V7 on the pre-cadence slot, then the new tonic
on the cadence bar — falling back to a direct V7 when the keys share no
triad. `wander_phrases=N` walks the key ±1 fifth automatically with a spring
back toward home.

## Setup

Requires Python 3.12+ and, for audio, FluidSynth with a General MIDI
soundfont (Debian/Ubuntu: `apt install fluidsynth fluid-soundfont-gm`;
default soundfont path: `/usr/share/sounds/sf2/FluidR3_GM.sf2`).

```sh
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,live]"   # live extra = python-rtmidi (Linux/ALSA)
.venv/bin/python -m pytest               # 190 tests
```

The generation core is stdlib-only; `mido`/`rtmidi` are confined to the MIDI
I/O boundary (`midi_io.py`, `live.py`).

## Demos

All demos write `.mid` + `.wav` + annotated `.txt` dump + `.trace.txt` into
`out/` and fail loudly on any theory-lint violation. Common flags: `--seed N`
and `--no-audio`; most accept `--bars N`, and the single-render demos take
`--play`.

| Script | What it shows |
|---|---|
| `demos/demo_journey.py` | **Flagship**: ~3 min scripted scenario — explore → threat → combat → victory → calm — driven purely through the levers, no hard cuts |
| `demos/demo_live.py` | Real-time playback through FluidSynth with the levers on the keyboard (`a/z` `s/x` `d/c` nudge, `1–5` act presets, `o/l` tempo override, `m/n` modulate a fifth). `--selftest 8` verifies the audio chain hands-free |
| `demos/demo_modulation.py` | Pivot-chord key changes: scripted requests (C → G → Eb → urgent snap home) plus the automatic wander policy — dumps annotate the pivot in both keys |
| `demos/demo_meters.py` | The same seed and lever arc in 4/4, 3/4 (waltz), and 6/8 (compound: two dotted-quarter pulses drive drums, bass, melody, and accents) |
| `demos/demo_instruments.py` | Energy staircase through the instrument tiers — pad/bass/melody/arp each swap patches at their own threshold, with hysteresis staggering the way back down. Notes identical; only timbre moves |
| `demos/demo_axes.py` | 3×3 grid over (valence × energy) at fixed seed — hear each axis in isolation |
| `demos/demo_tension.py` | Tension swept 0 → 1 → 0: watch cadences shift authentic → half → deceptive and extensions accumulate |
| `demos/demo_seeds.py` | Same levers, five seeds — variety under identical control |
| `demos/demo_modifiers.py` | Dry / default / wet modifier chains over identical notes |
| `demos/m2_full.py` | Full texture at static levers (`--mode aeolian --valence -0.7` is a good time) |
| `demos/m1_harmony.py` | Harmony backbone only: progression walk + voice-led pad + bass |
| `demos/m0_smoke.py` | Minimal pipeline check: hardcoded I–IV–V–I through MIDI/dump/audio |
| `demos/demo_synth.py` | The journey through the **signalflow synthesis backend** (`pip install -e ".[synth]"`): subtractive/FM voices, lever-driven filter/send/drive automation, per-strip EQ, bus chorus, ping-pong delay, hand-rolled FDN reverb, sidechain ducking, lookahead limiting, dithered export. `--live` plays in real time. See `SYNTHESIS.md` |

Example:

```sh
.venv/bin/python demos/demo_journey.py && paplay out/journey_s42.wav
.venv/bin/python demos/demo_live.py        # interactive; q quits
```

## Using the engine directly

```python
from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine

engine = MusicEngine(seed=42, config=EngineConfig(mapper=MappingTable()))
engine.set_affect(valence=-0.5, energy=0.8, tension=0.7)  # any time, any rate
engine.set_override("tempo_bpm", 120.0)                   # pin one parameter
engine.request_key("Eb", urgent=True)                     # pivot-chord modulation

bar = engine.advance_bar()   # BarResult: events (post-modifier), raw_events,
                             # context (key/mode/chord), params, tempo_points, trace
```

This pull-based contract — plus per-bar seeding (save/resume and replay come
free) — is the piece intended to port into the engine proper.

## Layout

```
musicgen/
├── ir.py            # NoteEvent (theory-annotated), Meter, HarmonicContext, MusicalParams
├── rng.py           # deterministic per-(subsystem, bar) seed streams
├── theory/          # pitch, scales/modes (brightness axis), chords (roman numerals,
│                    #   borrowing), functional harmony walk, voice-leading search,
│                    #   pivot-chord modulation
├── gen/             # conductor (MusicEngine), structure/phrases, rhythm (Euclidean,
│                    #   roughness), pad, bass, melody (motifs), arp, perc
├── control/         # affect levers, THE mapping table, automation curves
├── modifiers/       # strum, humanize, articulate, accent, echo, swing, transpose
├── midi_io.py       # SMF writer/reader (the mido boundary)
├── textdump.py      # annotated bar dumps + flat event lists
├── verify.py        # theory linter: scale/chord membership, voice leading,
│                    #   melody rules, cadence realization — pre & post modifier
├── audition.py      # FluidSynth render/playback helpers
├── clock.py         # BeatClock: beats -> seconds through the tempo map
├── live.py          # real-time MIDI player: look-ahead scheduler, ports
└── synth/           # signalflow DSP backend: voices, console (buses/sends/
                     #   reverb/ducking/master), offline + realtime renderers
                     #   -> doubles as the C-audio-library spec, see SYNTHESIS.md
demos/               # the scripts above (+ common.py emission pipeline)
tests/               # pytest suite
out/                 # renders (untracked)
research.md          # background survey the design distilled from
```

## Status

Prototype; the base feature set is complete — theory-driven generation,
affect levers, modifiers, live mode, the signalflow DSP backend, real key
modulation (pivot chords), triple and compound meters (3/4, 6/8, 12/8), and
energy-driven instrument swaps. What remains is deepening the DSP vocabulary
(roadmap in `SYNTHESIS.md`).
