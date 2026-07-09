# REFINEMENT_PLAN.md — from *correct* to *intended* (post-M17)

The improvements.md laundry list, distilled into an ordered implementation backlog.
Goal: bring the composition to a mature level of perceived intent **before** the
theory + technical spec for the C engine is drafted, so the spec freezes over a
finished IR and rule set instead of one we know is missing pieces.

**Ordering principle.** Items are ranked by payoff ÷ technical complexity, with
prerequisites hoisted ahead of their dependents. Two adjustments on top of the raw
ratio: (1) items with equal ratios are grouped by theme so the same files aren't
churned twice; (2) items that reshape the **IR or the architecture** (tie flag, new
layer, phrase clock, sub-bar harmony) are *spec-gating* — they are deliberately kept
in the plan's tail but they are **not optional**: the C spec cannot freeze before
they land, because they change the event format, the per-bar context shape, and the
pull-loop contract that §13 exports.

**House invariants — every item below inherits these** (they are what made
M13–M17 safe):

- **Config-gated, byte-identical off.** Each feature gets an explicit toggle
  (in its layer config, `DramaturgConfig`, or a new `PerformConfig`); the disabled
  path reproduces today's output byte-for-byte. This is the DoD's regression anchor.
- **Determinism.** All randomness from `Seeder.stream(subsystem, bar|phrase)`;
  phrase-scope decisions cached in `ConductorState` like `motifs`/`phrase_policies`.
- **Traced.** Every new decision emits a trace line ("why did it play that?").
- **Linted, with a poisoned plant.** Every rule the generator obeys becomes a
  `verify.py` rule, and every obligation-style rule gets a test that plants a
  deliberate violation and asserts the linter catches it (the M14 discipline).
- **Playground-tunable** where the constant is a by-ear judgment call.
- Lands as a PLANS.md milestone entry (M19+) when done; tests + a demo per wave.

**Branch note.** The uncommitted DX-1413a wind-texture voices (patches/console/
midi_io) are orthogonal to everything here — land or park that branch first so
these waves start from a clean baseline.

---

## Ranked backlog at a glance

| # | Item | Complexity | Payoff | Hard prereqs | Spec-gating |
|---|------|-----------|--------|--------------|-------------|
| A1 | Phrasing / performance shaping ✚ *(done)* | S | ★★★★★ | — | no |
| A2 | Groove persistence contract ✚ *(done)* | S | ★★★ | — | no |
| A3 | Outer-voice counterpoint (lint + guards) ✚ *(done)* | S–M | ★★★★ | — | rules → spec |
| A4 | Single-apex contour planning ✚ *(done)* | S | ★★★ | — | no |
| B1 | Cadential 6/4 (prepared authentic cadence) | S | ★★★★ | — | no |
| B2 | Antecedent–consequent periods | M | ★★★★★ | — | planner → spec |
| B3 | Hypermetric weight | S | ★★★ | — | no |
| B4 | Bass-line planning (inversions, lament bass) | M | ★★★★ | B1, A3 | no |
| C1 | Parallel doubling in 3rds/6ths | S | ★★★ | A3 | no |
| C2 | Inner-voice animation (pad figuration) | S–M | ★★★★ | — | no |
| C3 | Imitation | M | ★★★★ | A3 | no |
| C4 | Texture as a Tier-2 parameter | S–M | ★★★★ | ≥2 of C1–C3 | param set → spec |
| C5 | Countermelody + guide-tone lines | L | ★★★★★ | A3, C4 | **yes** (new layer) |
| D1 | `tie` flag: anacrusis, cross-bar suspensions | L | ★★★★ | — | **yes** (IR) |
| D2 | PhraseClock: codetta / extension / elision | L | ★★★★ | B2 | **yes** (loop contract) |
| D3 | Intra-bar harmonic rhythm (2 chords/bar) | XL | ★★★ | — | **yes** (context shape) |

Improvements.md's own "prototype these first" pick — phrasing, periods,
countermelody — maps to A1, B2, C5: first, sixth, and the polyphony capstone. The
ordering honors it; the items between them are their prerequisites or share their
files.

---

## Wave A — the performed surface (no structural change)

Four independent, small items. Everything here is a pure function of state the
engine already has; none of it moves the IR.

### A1. Phrasing / performance shaping — the "sequenced vs played" delta ✚ *(done; PLANS.md M19)*

**Payoff ★★★★★ / Complexity S.** Improvements.md's own bet for highest perceived
quality per effort, and I agree: Humanize is noise; this is *systematic* deviation
tied to structure, fully deterministic (no RNG at all).

**Design.**
- Add phrase awareness to the modifier surface: `HarmonicContext` gains
  `phrase_pos: int` and `phrase_bars: int` (the conductor has `pos` in hand at
  ctx-construction; additive field, nothing downstream breaks). Modifiers can
  already see `cadence_slot`; now they can see where in the phrase they are.
- New modifier `Perform` (first in the chain, before Articulate/Accent/Humanize),
  with a frozen `PerformConfig` (fields all playground-tunable):
  - **Velocity hairpin**: scale velocity by a phrase-position curve rising into
    `bars-2` and relaxing at the cadence (once A4 lands, drive the crest by the
    planned apex bar instead of position).
  - **Contour-tracking velocity**: `velocity += k·(pitch − register_center)`,
    k ≈ 0.3–0.5, melody/counter layers only.
  - **Agogic lengthening**: the cadence bar's final (target) note and phrase-open
    downbeat notes get `dur × 1.05–1.10` (safe pre-Articulate).
  - **Luftpause**: shorten the cadence bar's *last* sounding notes by 0.03–0.06
    beats so a sliver of silence precedes the next phrase downbeat. (Implemented
    forward from within the cadence bar — no cross-bar reach needed.)
  - **Lay-back/push**: melody starts shifted by ±0.01–0.02 beats, sign and size a
    function of energy (behind the beat when calm, on top when driving).
- **Micro-ritardando** is conductor-side, not a modifier: in `advance_bar`, when
  `pos.slot == "cadence"` (and policy is authentic, or a dramaturg spend), scale
  that bar's tempo points down 1–3% across the bar and emit a recovery point at
  the next bar start. Emit these in both mapper and static paths, gated by
  `PerformConfig.enabled`. Scale the rit by `ledger.last_spend` when the dramaturg
  is on — a bigger payoff breathes longer.

**Files.** `ir.py` (+2 ctx fields), `modifiers/__init__.py` (Perform),
`gen/conductor.py` (ctx fields, rit, default chain insertion), `control/mapping.py`
or a new `PerformConfig` home, playground schema.

**Lint/tests.** Post-stage timing bounds extended to cover Perform's shifts (like
Humanize's). A/B test: same seed with/without ⇒ pre-modifier IR identical.
Determinism: two renders bit-identical. Demo: `demo_perform.py` A/B.

**Risks.** Tempo-point consumers (midi writer, `synth/render.py`, `live.py`,
playground) must all tolerate >1 point per beat — verify each; the writer already
accepts arbitrary `(beat, bpm)` lists.

### A2. Groove persistence as an explicit contract ✚ *(done; PLANS.md M19)*

**Payoff ★★★ / Complexity S.** Pattern identity is what makes harmonic change
legible. Today it holds only by accident: kick E(k,16) and hat step are pure
functions of params, but **ghost snares, hat drops, and open-hat substitutions
re-roll every bar** from `stream("perc", bar)`.

**Design.** Split pattern-defining draws from embellishment draws, the way the arp
already does (`stream("arp-pattern", phrase)`):
- `ConductorState.grooves: dict[int, Groove]` cache (like `motifs`), built at each
  phrase's first bar from that bar's params: ghost-slot set, hat drop mask, ohat
  choice — drawn once from `stream("perc-pattern", phrase)`.
- Per-bar stream keeps only: fill trigger, fill pattern choice.
- Arp: also pin the per-bar `skip` mask per phrase (same treatment), keep nothing
  else stochastic per bar.
- Gate: `PercConfig.phrase_groove: bool` (off ⇒ byte-identical today).

**Lint.** New rule: within a phrase whose (density, roughness, layers) are
constant, non-fill perc events are bar-to-bar identical; verify on the automated
sweeps. This pins the contract the C engine should inherit.

### A3. Outer-voice counterpoint — lint + generation guards ✚ *(done; PLANS.md M20)*

**Payoff ★★★★ / Complexity S–M.** The soprano–bass frame carries tonal music and
is currently unguarded: nothing prevents parallel 5ths/8ves between melody and
bass, or both outer voices leaping the same way into a downbeat. Raises perceived
craft *now* and is a hard prerequisite for every polyphony item (C1/C3/C5 need the
same interval machinery).

**Design.**
- New `theory/counterpoint.py`: interval classification (perfect/imperfect
  consonance, dissonance), motion classification (parallel/similar/contrary/
  oblique), `forbidden_parallel(prev_pair, next_pair)`, and a consonance table —
  pure functions, directly portable, **this file is a chunk of the C spec**.
- Generation guards (cheap, local):
  - `generate_melody._place`: when snapping a strong beat to a chord tone, the
    candidate that forms a parallel P5/P8 with the bass's beat-1 pc (already known:
    `ctx.chord_pcs[0]` this bar and last — thread `prev_bass_pc` through) is
    deprioritized in `_nearest_pc_pitch`'s tie-break.
  - `_cadence_bar`: choose the target octave/approach direction contrary to the
    bass's root motion into the cadence (bass motion is known from
    `ctx.chord_pcs[0]` vs `next_chord.bass_pc`).
- Lint (`verify._lint_outer_voices`): scan strong-beat (melody, bass) pairs for
  consecutive perfect parallels and for similar-motion leaps into a downbeat
  landing on a perfect interval (direct 5ths/8ves); contrary/oblique preferred into
  cadence bars (ratio rule with slack, like leaps).

**Risks.** The lint will almost certainly flag today's output — land guards and
lint in the same change, run the seed-sweep tests, and tune the guard until the
sweep is clean before enabling the rule by default.

### A4. Single-apex contour planning ✚ *(done; PLANS.md M19)*

**Payoff ★★★ / Complexity S.** One melodic peak per phrase, approached by leap-up,
left by stepwise fill (gap-fill). Complements the dramaturg's ambit cap (which is
the *withholding* rule; this is the normal-operation rule).

**Design.**
- Per-phrase apex plan cached in `ConductorState` (dict like `motifs`), drawn from
  `stream("apex", phrase)`: apex bar (weighted toward `bars−3`/`bars−2`, matching
  the §5.6 micro-arc peak) and apex pitch (upper third of the register window).
- `generate_melody` receives the plan: pre-apex bars cap `hi` at `apex−1` (compose
  with the dramaturg's `register_cap` via `min`); the apex bar biases one strong
  contour note to the apex (offset override in `_place`); post-apex bars bias the
  anchor downward (gravity already exists — strengthen it).
- Under a `completed`/landmark signature phrase, the plan stands down — the
  cadence-fused statement owns that phrase's shape.

**Lint.** Soft first: a per-phrase "apex count" metric in the trace/dump; promote
to a lint rule (exactly one apex-bar cluster per phrase, melody present) once the
sweeps are clean.

---

## Wave B — coherence: periods, prepared cadences, hypermeter, the bass as a voice

### B1. Cadential 6/4

**Payoff ★★★★ / Complexity S.** The single missing cadence idiom that makes
authentic cadences read as *prepared*. Fully representable today —
`Chord(1, inversion=2)` exists, `chord_pcs` is bass-first, the bass and linter
already respect inversions.

**Design.**
- In `_gen_chord`: when the phrase's policy is authentic (mapper choice or
  dramaturg spend) and tension is mid+, realize the **`bars−3` free bar** as
  `Chord(1, inversion=2)` → pre-cadence `V(7)` → cadence `I`. The bass line comes
  free: pc(5̂) → pc(5̂) → pc(1̂) — the classical dominant-anchored 6/4 bass.
- Trace: `cadential 6/4 → V → I`. Symbol pretty-print: render inversions as
  figures (`I64`, `I6`) instead of `/2` in `Chord.symbol`.
- Obligation: stamp `ctx.obligation = "cadential64"` on the 6/4 bar; the linter
  verifies a dominant follows (same pattern as `tonicize:N`). Poisoned-plant test.
- Interacts with M14: the suspension machinery already ornaments these cadences;
  the 6/4's 4th-over-bass *is* conceptually the suspension — no special-casing
  needed since pad lint checks chord membership against `chord_pcs`.

**Files.** `theory/harmony.py`, `theory/chords.py` (symbol), `gen/conductor.py`,
`verify.py`.

### B2. Antecedent–consequent periods

**Payoff ★★★★★ / Complexity M.** Improvements.md is right that this is the
strongest "a mind composed this" signal available, and the machinery is 70%
present: per-phrase motif cache, per-phrase cadence policies, cadence rationing.

**Design.**
- New `PhrasePlanner` in `ConductorState` (this object is later extended by D2 —
  design it as the one owner of phrase-level form): at each even phrase boundary
  (when no modulation window overlaps and the dramaturg is idle or releasing),
  commit a **period**: phrase N = antecedent (forced `half`), phrase N+1 =
  consequent (forced `authentic`).
- Route through `_policy` with explicit precedence, documented in one place:
  **modulation > override > dramaturg > planner > cycle/mapper**. The dramaturg
  outranking the planner is the musical truth: while withholding, the consequent's
  PAC becomes another deception and the period rolls forward — and a **dramaturg
  spend aligned to a consequent is the jackpot**: consequent PAC + cadential 6/4 +
  M15 cadence-fused statement + mode brightening, all one arrival.
- **Parallel openings**: `_motif()` aliases the consequent's phrase to the
  antecedent's motif (one-line planner check). For "opens identically" beyond the
  motif: record the antecedent's bar-0 placed `(slot, dur, pitch)` list in the
  planner; at consequent bar 0, if the chord matches, replay it verbatim
  (re-annotated); else re-run `_place` with the anchor pinned to the antecedent's
  opening anchor. Rhythm + contour identity is what the ear pairs; near-identical
  pitches suffice.
- Signature interplay (M15/M17): the signature slot (`bars//2`) fires in both
  phrases — that's a feature (introduced in the antecedent, developed in the
  consequent = the compounding improvements.md predicts). A landmark forcing
  authentic on an antecedent breaks the half cadence — planner defers to it
  (precedence above) and simply doesn't pair that phrase.

**Lint.** Period contract: when the planner commits a period, phrase N ends on
degree 5 (`half` realized), N+1 on degree 1, and bar-0 rhythms match. Trace both
the commitment and any override that broke it.

**Demo.** `demo_periods.py`: static mid levers, planner on/off A/B — the QA
call-and-answer should be blind-obvious.

### B3. Hypermetric weight

**Payoff ★★★ / Complexity S.** Bars within the group get the weight treatment
slots already have.

**Design.**
- `structure.hyper_weight(pos) -> float`: 4-bar group profile (e.g. 1.0 / 0.4 /
  0.7 / 0.3), generalized over `phrase_bars` (8 = two 4-groups; the mid-phrase
  bar is the second-strongest — which retroactively justifies the M15 signature
  slot at `bars//2`).
- Consumers, in one pass: **roughness** scaled up on weak bars / down on strong
  (syncopation licensed off the strong bars) in `advance_bar` before generators
  run; **held-chord placement** for slow harmonic rhythm prefers holding into weak
  bars (generalize the current `bar % 2 == 1`); **Perform (A1)** adds a small
  hyper-accent to bar downbeats by weight; **fill probability** slightly raised
  into hyper-strong boundaries.

**Lint.** None new — existing sweeps must stay clean; A/B dump shows the roughness
modulation.

### B4. Bass-line planning: inversions and the lament tetrachord

**Payoff ★★★★ / Complexity M.** Turns the bass from a root-reporter into a voice.
Prereqs: B1 (inversion plumbing proven at the cadence), A3 (parallels shift when
the bass moves by step — the lint must be watching first).

**Design.**
- **Greedy stepwise bias** (fits the 1-bar lookahead; no phrase-scope replanning
  needed): in `_gen_chord`, after the walk picks a degree, score inversions
  {root, 6, (64 rare)} by bass-pc step distance from the previous bar's bass pc;
  prefer steps ≤2 semitones; penalties: any inversion on open/cadence bars, 6/4
  outside the cadential formula, >2 consecutive inverted bars. Trace each choice.
- **Lament tetrachord as an escalation rung**: while withholding at rung ≥ 2, the
  dramaturg alternates buildups between the dominant pedal (M14) and a descending
  diatonic tetrachord bass 1̂–7̂–6̂–5̂ realized via inversions (i – v6 – iv6 – V in
  minor-side modes), terminating on the dominant exactly where the pedal would sit.
  Deterministic choice (by buildup index parity). The `phrase_cadence` and pedal
  obligations machinery already cover the discharge.
- Voicing note: pad voicing uses root-first `pitch_classes` (upper voices free
  over any bass) — already correct for inversions; nothing to change.

**Lint.** Bass beat-1 = `chord_pcs[0]` already enforces inversion honesty. Add:
tetrachord obligation (a planted lament run must reach the dominant), plant test.

---

## Wave C — the polyphony ladder (cheap → dear)

The core ask. Ordered exactly as improvements.md ascends: doubling → inner-voice
animation → imitation → texture parameter → countermelody. A3's
`theory/counterpoint.py` underpins all of it.

### C1. Parallel doubling in 3rds/6ths

**Payoff ★★★ / Complexity S.** Cheapest polyphony in existence; reads as richness,
not as a second voice — so it stays **inside the melody layer** (same channel/
patch, slightly lower velocity), no new-layer infrastructure.

**Design.**
- Post-pass in `generate_melody` (gated by texture C4 once it exists; interim gate:
  valence > 0.3 ∧ energy > 0.55): for each melody note, add a note a diatonic 3rd
  below, switching to a 6th when the 3rd is not a chord tone on a strong slot
  (whitelist: chord member on strong slots, scale member elsewhere).
  Role `"doubling"`, velocity −8.
- Exclude `"doubling"` from `_lint_melody`'s tuneful line (like `MOTIF_ROLE`) —
  interleaved doubles would otherwise fake leaps.

**Lint.** New rule: every doubling note is simultaneous with a melody note at a
3rd/6th (or compound) below, chord/scale membership per the whitelist. Plant test.

### C2. Inner-voice animation (figurated homophony)

**Payoff ★★★★ / Complexity S–M.** Most of what registers as polyphony in media
music. Directly attacks pad stasis at low energy — where the pad is often the only
layer sounding, so this is disproportionately audible.

**Design.**
- The pad already knows its target voicing and returns it as memory; give it the
  *next* one: conductor passes `next_pcs` (computed against `next_scale`, the same
  way the bass gets `next_bass_pc`), pad computes `voice_chord(next_pcs, voicing)`
  — deterministic preview of where each voice is going.
- Two figuration modes by energy (config-gated `VoicingConfig.animate`):
  - **Connective**: one voice (prefer the one moving a 3rd) walks a passing tone
    in the bar's second half toward its next-bar pitch. Role `"passing"` (already
    licensed in pad lint).
  - **Arpeggiated comping** at mid energy: realize the voicing as a slow
    `rough_cell` figure (half-note grid) instead of a block — Alberti-adjacent,
    chord tones only, so lint-neutral.
- The returned `voicing` stays the block target (the suspension code already
  proves this pattern), so voice-leading memory and M14 preparation are untouched.

**Risk.** Interaction with suspensions: when `directive.suspend` fires, animation
stands down for that bar (the ornament owns the pad's attention).

### C3. Imitation

**Payoff ★★★★ / Complexity M.** The listener hears the voices *listening to each
other* — maximal intent per line of code. The machinery exists: motif cells,
`realize_faithful`, per-phrase caches.

**Design.**
- At phrase bars 1–2 (after the statement), restate the phrase motif's opening
  cell (first `⌈n/2⌉` notes — reuse `_introduce`'s fragment logic) in the **arp
  register** (or top pad voice when the arp is gated off/held by the dramaturg),
  offset +half-bar or +1 bar, at the diatonic transposition `realize_faithful`
  picks. Role `"imitation"` — licensed like `"motif"`, exempt from arp/pad
  chord-membership at weak slots but held to it on strong slots.
- **Collision rule** (deterministic, retry-list): at overlapping onsets, if the
  imitation note forms a 2nd/7th/tritone against the sounding melody note, try
  entry +half-bar later, then transposition ±3rd, then drop. The melody's IR for
  the bar exists before the arp runs — no lookahead needed.
- With a signature pending (M15/M17), imitate the *signature* cell instead — the
  identity echoes across layers, which is M15's deferred "passed between layers"
  item landing for free.

**Lint.** Imitation events must match the source cell's contour (reuse
`recognizability` ≥ threshold at the entry's transposition). Plant test.

### C4. Texture as a Tier-2 parameter

**Payoff ★★★★ / Complexity S–M.** Texture change is the strongest variety lever
human arrangers use, and it hands the dramaturg a new debt currency. Needs at
least two textures to exist (C1 + C2), hence its position.

**Design.**
- `MusicalParams.texture: str` ∈ {monophonic, homophonic, doubled, imitative,
  counter} (counter joins at C5). Mapper: base choice by (valence, energy);
  **phrase-boundary rotation with memory** — never the same texture twice in a
  row, occasionally return to the one from two phrases ago (draw from
  `stream("texture", phrase)`, cached like `phrase_policies`). Overridable
  (`levers.OVERRIDABLE` picks it up automatically from the dataclass fields).
- Consumers: C1's gate, C2's mode, C3's on/off, later C5's gate. `monophonic`
  thins the pad to root+fifth dyads at low energy (a real texture, free).
- **Dramaturg texture debt**: while withholding, clamp texture to homophonic
  (withhold the interesting textures alongside the arp tier); the spend releases
  the richest texture available — one more thing that snaps in on the payoff.
- Trace + dump line: `texture: doubled (rotation, last=homophonic)`.

**Lint.** Texture claims are checkable: `doubled` ⇒ doubling events exist;
`imitative` ⇒ an imitation entry exists in the phrase; etc. Cheap and honest.

### C5. Countermelody generator + guide-tone lines

**Payoff ★★★★★ / Complexity L.** The polyphony capstone, and — in keeping with
how everything in this project has been treated — its real deliverable is the
**species-rule set in verify.py**, which is a reusable spec for the C engine.

**Design.**
- **Guide tones first** (`theory/guides.py`, S-sized): thread the 3rds and 7ths of
  successive chords into a minimal-motion line (`guide_line(chords, scale) →
  per-bar target pcs`). Emit it in the dump as an annotation line. This is both a
  coherence probe and the counter's skeleton.
- **New layer** — the one-time infrastructure cost, itemized:
  `ir.LAYER_NAMES` +"counter"; `midi_io.LAYER_MIDI` channel 4 + GM program (e.g.
  71 clarinet / 42 cello) + `GM_PATCHES` tiers; a synth voice (reuse `lead_voice`
  with a softer variant initially); `console` dispatch arm; `mapping.layer_gates`
  entry (energy ≳ 0.45 *and* texture == counter); `default_chains` (articulate +
  accent + humanize); `LintLimits.counter_range`; textdump ordering; playground
  schema/strip. Budget a day for just this sweep.
- **Generator** (`gen/counter.py`), constraint-first like everything else — the
  melody IR for the bar already exists when it runs:
  1. **Rhythmic complementarity**: derive the bar's onset-gap profile from the
     melody events; place counter onsets in the holes (move where the melody
     holds, hold where it moves). A `rough_cell` at reduced density masked
     against melody onsets does this in ~10 lines.
  2. **Strong beats**: consonant with *the melody* (3rd/6th/10th preferred, P5/P8
     rationed) **and** a chord member; seed strong-beat pitches from the
     guide-tone line, deviate only when register or motion rules force it.
  3. **Motion**: contrary/oblique preferred vs melody (scored via
     `theory/counterpoint.py`); no parallel perfects against melody **or** bass;
     no similar motion into a perfect interval on a downbeat.
  4. Register: the tenor gap between bass and melody (~G3–G5), soft gravity like
     the melody's.
- Gated as a texture state (C4) the dramaturg can withhold and spend — release of
  the countermelody *is* a payoff gesture.

**Lint.** The full species set, each with plant tests: strong-beat consonance
ratio vs melody; parallel-perfect prohibition (three-way: counter/melody,
counter/bass — A3 already covers melody/bass); complementarity metric (onset
overlap on non-downbeat slots below a threshold); range and voice-crossing vs
melody.

**Demo.** `demo_texture.py`: one seed, texture rotation across all five states,
plus a dramaturg buildup where the counter is withheld and released.

---

## Wave D — IR-level structure (spec-gating; do before the C spec freezes)

These three are the expensive ones, but they are precisely the items that decide
what the C engine's event format, per-bar context, and pull-loop contract look
like. Landing them here means the spec is written from experience, not prediction.

### D1. `tie` flag on NoteEvent — anacrusis, cross-bar suspensions, cross-bar syncopation

**Payoff ★★★★ / Complexity L.** M8's "raw events never cross barlines" invariant
quietly forbids the pickup and the tied suspension — the two most human gestures
missing. One IR change unlocks both while *preserving* the invariant (tied halves
stay grid- and bar-legal).

**Design.**
- `NoteEvent.tie: str = ""` ∈ {"", "out", "in", "both"} — "out" continues into the
  next same-pitch event; "in" continues from one. A **chain** = consecutive
  same-layer same-pitch events with matching end/start and flags.
- Consumer sweep (the real cost — checklist, each with a test):
  - `midi_io.write_midi`: merge chains into one note_on/off pair;
    `verify_roundtrip` compares merged musical notes.
  - `verify.py`: melody line rules (leaps, strong-beat ratio) and obligation
    checks operate on merged chains; grid checks stay per raw event.
  - `modifiers`: Articulate scales only chain-final segments; Humanize never
    jitters interior joins (`tie in` events keep their start); Echo echoes the
    merged note once; Strum/Accent unaffected.
  - `textdump`: render ties (`D5~`), chains counted once in stats.
  - `live.py`: suppress note_off for "out" and note_on for "in" — MIDI-natural.
  - `synth/console.py`: offline render merges before voice dispatch; **realtime
    path re-articulates ties in the first cut** (one-shot envelopes can't extend
    retroactively) — documented, revisit if audible.
- **Features on top**, in order:
  1. **Anacrusis**: in the cadence bar, the melody may emit 1–3 pickup 8ths/16ths
     (post-luftpause) stepping toward the next bar's chord root/3rd (known from
     `next_chord`), the last tied into the downbeat when it lands on it. No
     next-phrase motif knowledge needed — approach-by-step reads as a pickup
     regardless of what follows. Probability by energy, from `stream("pickup",
     bar)`.
  2. **Cross-bar suspension preparation**: `Directive.suspend` already fires at
     the pre-cadence bar; the pad computes the *next* bar's voicing + suspension
     pair deterministically (same preview as C2), and ties the preparation voice
     across the barline. The M14 linter's preparation check gets *stronger*
     (a genuinely held tone, not a re-struck one).
  3. **Cross-bar syncopation**: `rough_cell` may merge the bar's last 8th into
     the next bar's downbeat (emitted as tied halves) at high roughness.

**DoD.** Byte-identical with no ties emitted; round-trip clean; all 272+ tests
pass; the "phrase starts are bar-aligned" tell is audibly gone in the A/B.

### D2. PhraseClock — codetta, extension, elision

**Payoff ★★★★ / Complexity L.** Everything is 4 or 8 bars today because
`phrase_position()` is a pure div/mod. Humans elide, extend, and append codettas;
the dramaturg is the natural author of all three.

**Design.**
- Replace computed phrase position with a **scheduled `PhraseClock`** owned by the
  B2 `PhrasePlanner`: a list of `(start_bar, bars, kind)` segments; default
  schedule = fixed `phrase_bars` (byte-identical). `structure.effective_tension`'s
  `ARCS` generalizes to a parametric arc over `bars` (rise to `bars−2`, settle).
- Sweep of pos-keyed logic onto the clock: dramaturg decisions at pos 0, signature
  slot `bars//2`, arp per-phrase pattern, motif cache keys, cadence slots,
  wander spacing. Mechanical but wide — this is most of the cost.
- Three moves, in increasing risk order, all dramaturg/planner-authored + traced:
  1. **Codetta** (safest): after a spend with `payoff ≥ threshold`, append a
     2-bar `kind="codetta"` segment — tonic prolongation (I, maybe plagal IV–I),
     melody echoes the cadence statement's tail an octave up (`realize_faithful`
     on the last 2–3 notes), percussion thinned. Payoffs breathe instead of
     re-entering the loop.
  2. **Extension**: while withholding at high tension, stretch the pre-dominant —
     insert 2 bars before the cadence pair (the deceptive cadence arrives *late*;
     debt accrues by the same bars-based ledger arithmetic automatically).
  3. **Elision** (riskiest): at high energy, the cadence bar *is* the next
     phrase's bar 0 — model as overlapping segments where the downbeat carries
     both the resolution and the new opening (crash + phrase-open tonic boost
     coincide). Gate behind its own toggle; extensive sweep tests.

**DoD.** Default schedule byte-identical; codetta/extension/elision each A/B
demoed; lint clean across seeds × meters; the ledger's monotone-payoff property
still holds with elastic phrases (re-run `demo_payoff` acceptance).

### D3. Intra-bar harmonic rhythm (2 chords/bar)

**Payoff ★★★ / Complexity XL.** The `harmonic_rhythm=2` cell of the §6.2 table
that never landed, and the *true* form of cadence-approach acceleration (B1's
3-bar formula is the 80% version). Ranked last: most architecture for the least
marginal music — but the **context-shape decision it forces (one chord per bar
vs a chord timeline) is the last open IR question for the C spec**, so it must be
settled (even if the answer is "one chord per bar, acceleration via B1, spec says
so").

**Design sketch (decision record even if deferred).**
- `HarmonicContext.chords: tuple[(beat_offset, Chord), ...]` with `chord` kept as
  the downbeat alias for compatibility; `chord_queue` entries carry per-half-bar
  chords when the (energy+tension) gate opens, and at the pre-cadence bar for the
  one-bar 6/4→V.
- Generators consume the timeline: pad re-voices at the half-bar (voice-leading
  memory per segment), bass roots per segment, melody strong-slot membership per
  segment, arp pool switch, lint chord rules windowed per segment.
- Recommendation: prototype on the pre-cadence bar *only* (the musical payoff
  concentrates there), measure whether general 2/bar earns its complexity, then
  write the spec from the result.

---

## Dependency graph

```
A1 Perform ──────────────┐
A2 Groove ───────────────┤  (independent)
A3 Counterpoint utils ───┼──→ C1 Doubling ──┐
A4 Apex ─────────────────┘                  ├─→ C4 Texture ─→ C5 Countermelody
                    C2 Pad animation ───────┘        ↑              ↑
B1 Cadential 6/4 ──→ B4 Bass planning       C3 Imitation ───────────┘
B2 Periods (PhrasePlanner) ──────────────→ D2 PhraseClock
B3 Hypermeter (independent)
D1 Tie flag (independent; strengthens M14 suspensions, B2 pickups)
D3 Intra-bar harmony (independent; decision gated on B1 experience)
```

M16 (foreshadow) and M18 (multi-bar signatures) from PLANS.md interleave freely:
M18 benefits from B2 (a period *is* a two-phrase identity — the natural first
multi-bar signature) and D1 (themes with pickups); M16 stays last, gated on the
game side as planned.

## Suggested milestone mapping

- **M19 — The performed surface**: A1 + A2 + A4 (one wave, one demo, mostly
  additive). *Small, ships in days, biggest single listening jump.*
- **M20 — Outer-voice craft**: A3 (guards + lint + `theory/counterpoint.py`).
- **M21 — Question & answer**: B1 + B2 + B3 (prepared cadences inside periods
  over hypermetric weighting — one coherent formal-craft milestone).
- **M22 — The bass as a voice**: B4.
- **M23 — Polyphony I**: C1 + C2 + C3 (textures exist).
- **M24 — Polyphony II**: C4 + C5 (texture parameter + countermelody + species
  linter; the C-spec's counterpoint chapter falls out of this one).
- **M25 — The barline falls**: D1.
- **M26 — Elastic form**: D2.
- **M27 — Harmonic-rhythm decision**: D3 prototype + decision record.

## What must land before the C-engine spec freezes

The spec's IR chapter needs **D1** (tie semantics), **C5** (final layer set),
**C4** (final Tier-2 parameter list), and **D2** (whether phrase length is a
constant or a scheduled clock — this changes the engine's phrase API). **D3**
needs at least its decision record. **A3 + C5's linter rules** are the acceptance
suite §13.3 promises the native implementation. Everything else (A1's constants,
B-wave heuristics) ports as tuning, not architecture — it can keep evolving in the
prototype after the spec drafts.
