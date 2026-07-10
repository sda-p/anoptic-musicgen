"""Motif-based melody engine (PLANS.md §5.5).

Each phrase owns one Motif (a rhythm cell from the roughness engine plus a
contour realized as diatonic offsets). Bars realize sentence-form variants of
it — statement, sequence, development ops, an ornamented pre-cadence drive,
and a cadence formula that converges on a policy-appropriate target degree.
A persistent signature (M15/M17) is staged *positionally* on top of that plan:
one signature event per phrase at the continuation onset while it matures, and
on the payoff the whole phrase develops the signature into a faithful statement
fused with the cadence (see generate_melody).

Pitch selection is constraint-first, never a free walk: strong beats snap to
chord tones, weak beats move by scale steps, leaps beyond a P4 recover by an
opposite step, and the register window folds pitches back toward center.
Over borrowed chords the melodic scale follows the chord's source mode; such
tones are labeled "borrowed" for the linter and the dump.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.gen.motif import realize_cadential, realize_faithful
from musicgen.gen.rhythm import rough_cell
from musicgen.gen.structure import PhrasePos
from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.counterpoint import forbidden_direct, forbidden_parallel
from musicgen.theory.pitch import pitch_name
from musicgen.theory.scales import Scale, diatonic_shift, snap_to_scale

CONTOUR_SHAPES = ("arch", "descent", "ascent", "zigzag")

# Cadence-bar melodic targets per policy, as context scale degrees, in
# preference order. Filtered to chord members at realization time.
CADENCE_TARGET_DEGREES = {"authentic": (1, 3), "half": (2, 5), "deceptive": (1, 3)}


@dataclass(frozen=True)
class MelodyConfig:
    range_semitones: int = 12
    bar_rest_max: float = 0.30
    span_min: int = 2
    span_max: int = 4
    plan_apex: bool = False  # A4: one planned melodic apex per phrase (off = byte-identical)
    counterpoint: bool = False  # A3: guard the melody-bass frame — strong-beat picks avoid
    #                             consecutive/direct perfects, cadences approach in contrary
    #                             motion (off = byte-identical)


@dataclass(frozen=True)
class ApexPlan:
    """Single-peak contour plan (REFINEMENT_PLAN A4): one melodic apex per
    phrase, approached by leap and left by stepwise fill. Every other bar caps
    its ceiling below the apex; the apex bar lifts its highest contour note to
    the planned pitch (chord-tone snapped), and the existing leap-recovery rule
    supplies the gap-fill descent for free. Cached per phrase in ConductorState
    (like motifs) — a pure function of (seed, phrase, phrase-start params)."""

    pos: int    # bar within the phrase carrying the apex
    pitch: int  # planned apex pitch — a hard ceiling minus one for the other bars


def make_apex(rng: random.Random, bars: int, center: int, range_semitones: int) -> ApexPlan:
    """The apex sits late (bars-3 / bars-2 — where the §5.6 micro-arc peaks) in
    the register window's upper third."""
    pos = max(1, rng.choices((bars - 3, bars - 2), weights=(0.45, 0.55))[0])
    lo_off = max(3, range_semitones * 5 // 12)
    return ApexPlan(pos, center + rng.randint(lo_off, max(lo_off + 1, range_semitones - 1)))


@dataclass(frozen=True)
class Motif:
    rhythm: tuple[tuple[int, int], ...]  # (slot, dur_slots) within one bar
    contour: tuple[int, ...]             # diatonic offsets from the bar anchor
    shape: str


@dataclass
class MelodyState:
    prev_pitch: int | None = None
    prev_anchor: int | None = None
    # (beat, melody pitch, bass pitch) at the last strong-slot melody onset —
    # the outer-voice pair the A3 guard continues from across the barline
    prev_outer: tuple[float, int, int] | None = None


def _contour_offsets(shape: str, n: int, span: int) -> tuple[int, ...]:
    if n == 1:
        return (0,)
    if shape == "arch":
        return tuple(round(span * (1 - abs(2 * i / (n - 1) - 1))) for i in range(n))
    if shape == "descent":
        return tuple(round(span * (1 - i / (n - 1))) for i in range(n))
    if shape == "ascent":
        return tuple(round(span * i / (n - 1)) for i in range(n))
    return tuple((i // 2) + (2 if i % 2 else 0) for i in range(n))  # rising zigzag


def make_motif(rng: random.Random, density: float, roughness: float, cfg: MelodyConfig,
               slots: int = 16) -> Motif:
    rhythm = rough_cell(rng, density, roughness, slots=slots)
    shape = rng.choice(CONTOUR_SHAPES)
    span = rng.randint(cfg.span_min, cfg.span_max)
    return Motif(rhythm, _contour_offsets(shape, len(rhythm), span), shape)


def _markedness(m: Motif) -> int:
    """How *distinctive* a cell is as an identity (§5.5, M15): a signature must be
    recognizable when it returns, which needs profile — not an undifferentiated
    pulse or a plain scale walk. One point each for motto length (4–7 notes),
    rhythmic differentiation (≥ 2 durations), a leap, a step, and a change of
    direction. `recognizability` measures whether a shape *survived* realization;
    this measures whether there is a shape worth surviving."""
    deltas = [b - a for a, b in zip(m.contour, m.contour[1:])]
    turns = [d for d in deltas if d]
    return sum((
        4 <= len(m.rhythm) <= 7,
        len({d for _, d in m.rhythm}) >= 2,
        any(abs(d) >= 2 for d in deltas),
        any(abs(d) <= 1 for d in deltas),
        any((a > 0) != (b > 0) for a, b in zip(turns, turns[1:])),
    ))


def make_signature(rng: random.Random, density: float, roughness: float,
                   cfg: MelodyConfig, slots: int = 16, attempts: int = 8) -> Motif:
    """A signature-grade motif (§5.5, M15): drawn like `make_motif` but from params
    clamped into the motto zone (a floor of rhythmic character even under a flat
    affect; a ceiling on density — a spray of 16ths doesn't gestalt), taking the
    most *marked* of `attempts` candidates, then repairing what the best draw still
    lacks: the tail merges into a held ending until the rhythm has profile and motto
    length, and a flat or monotone contour gets its midpoint lifted (creating the
    leap-and-turn). Deterministic for a given rng stream."""
    density = min(max(density, 0.5), 0.75)
    roughness = max(roughness, 0.3)
    m = max((make_motif(rng, density, roughness, cfg, slots=slots) for _ in range(attempts)),
            key=_markedness)
    while len(m.rhythm) > 7 or (len(m.rhythm) > 1 and len({d for _, d in m.rhythm}) < 2):
        (s1, _), (s2, d2) = m.rhythm[-2], m.rhythm[-1]
        m = Motif(m.rhythm[:-2] + ((s1, s2 + d2 - s1),), m.contour[:-1], m.shape)
    deltas = [b - a for a, b in zip(m.contour, m.contour[1:])]
    turns = [d for d in deltas if d]
    if not (any(abs(d) >= 2 for d in deltas)
            and any((a > 0) != (b > 0) for a, b in zip(turns, turns[1:]))):
        contour = list(m.contour)
        contour[len(contour) // 2] += 2
        m = Motif(m.rhythm, tuple(contour), m.shape)
    return m


# --- variation operators -----------------------------------------------------

def _sequence(m: Motif, steps: int) -> Motif:
    return Motif(m.rhythm, tuple(c + steps for c in m.contour), m.shape)


def _invert(m: Motif) -> Motif:
    return Motif(m.rhythm, tuple(-c for c in m.contour), m.shape)


def _displace(m: Motif, slots: int = 16) -> Motif:
    shifted = tuple((s + 2, d) for s, d in m.rhythm if s + 2 + d <= slots)
    if not shifted:
        return m
    return Motif(shifted, m.contour[: len(shifted)], m.shape)


def _truncate(m: Motif) -> Motif:
    if len(m.rhythm) <= 2:
        return m
    return Motif(m.rhythm[:-1], m.contour[:-1], m.shape)


def _ornament(m: Motif, rng: random.Random) -> Motif:
    idx = max(range(len(m.rhythm)), key=lambda i: m.rhythm[i][1])
    s, d = m.rhythm[idx]
    if d < 2:
        return m
    rhythm = m.rhythm[:idx] + ((s, d // 2), (s + d // 2, d - d // 2)) + m.rhythm[idx + 1:]
    contour = m.contour[: idx + 1] + (m.contour[idx] + rng.choice((-1, 1)),) + m.contour[idx + 1:]
    return Motif(rhythm, contour, m.shape)


def admissible_transforms(motif: Motif, slots: int = 16) -> list[tuple[str, Motif]]:
    """The transforms M17 may apply to fit an authored signature into an upcoming
    phrase (§5.5): identity plus inversion / displacement / truncation — widening
    where it drops in cleanly, without dissolving its identity."""
    return [
        ("identity", motif),
        ("inversion", _invert(motif)),
        ("displacement", _displace(motif, slots)),
        ("truncation", _truncate(motif)),
    ]


def phrase_variant(motif: Motif, pos: int, rng: random.Random, slots: int = 16) -> tuple[Motif, str]:
    """Sentence-form plan: statement, sequences, developments, ornament drive."""
    if pos == 0:
        return motif, "statement"
    if pos in (1, 4):
        step = rng.choice((-2, -1, 1, 2))
        return _sequence(motif, step), f"sequence{step:+d}"
    if pos == 3:
        return motif, "restatement"
    if pos == 6:
        return _ornament(motif, rng), "ornament"
    op = rng.choice(("invert", "displace", "truncate"))
    varied = {"invert": _invert(motif), "displace": _displace(motif, slots), "truncate": _truncate(motif)}[op]
    return varied, op


# --- pitch machinery ---------------------------------------------------------

def _pc_candidates(pcs, target: int, lo: int, hi: int) -> list[int]:
    """All in-range instances of the pcs, nearest-to-target first (ties break
    low). The head of this list is what _nearest_pc_pitch returns; the A3
    guard walks it looking for a counterpoint-clean pick."""
    out = [p for pc in set(pcs) for p in range(lo + (pc - lo) % 12, hi + 1, 12)]
    out.sort(key=lambda p: (abs(p - target), p))
    return out or [target]


def _nearest_pc_pitch(pcs, target: int, lo: int, hi: int) -> int:
    return _pc_candidates(pcs, target, lo, hi)[0]


class _OuterGuard:
    """Per-bar outer-voice guard (A3): mirrors verify.lint_outer's sampling —
    the (melody, bass) pair at strong-slot melody onsets — and steers strong
    chord-tone picks away from consecutive perfects (always) and direct
    perfects (into downbeats) against the realized bass. Falls back to the
    nearest candidate when every one is forbidden: the guard prefers, never
    fails. `prev` carries across bars via MelodyState.prev_outer and expires
    after a bar of silence, exactly like the linter's frame break."""

    def __init__(self, bass_events, bar_start: float, bar_len: float,
                 prev: tuple[float, int, int] | None,
                 prev_root: int | None = None) -> None:
        self.bass = [(e.start, e.end, e.pitch) for e in bass_events]
        self.bar_start = bar_start
        self.bar_len = bar_len
        self.prev = prev
        self.prev2: tuple[float, int, int] | None = None  # the pair BEFORE the last observe
        # the previous bar's realized downbeat bass — the cadence approach is
        # judged root-to-root across the barline (lint_outer's yardstick), and
        # the last strong PAIR may sit on a fifth or approach tone instead
        self.prev_root = prev_root

    def bass_at(self, t: float) -> int | None:
        cur = None
        for start, end, pitch in self.bass:
            if start > t + 1e-9:
                break
            if t < end - 1e-9:
                cur = pitch
        return cur

    def _pair(self, t: float) -> tuple[int, int] | None:
        if self.prev is None or t - self.prev[0] > self.bar_len + 1e-9:
            return None
        return self.prev[1], self.prev[2]

    def pick(self, pcs, target: int, lo: int, hi: int, slot: int) -> int:
        cands = _pc_candidates(pcs, target, lo, hi)
        t = self.bar_start + slot * GRID
        bass, pair = self.bass_at(t), self._pair(self.bar_start + slot * GRID)
        if bass is None or pair is None:
            return cands[0]
        prev_m, prev_b = pair
        for p in cands:
            if forbidden_parallel(prev_b, prev_m, bass, p):
                continue
            if slot == 0 and forbidden_direct(prev_b, prev_m, bass, p):
                continue
            return p
        return cands[0]

    def observe(self, slot: int, pitch: int) -> None:
        """Record the realized pair at a strong onset — whatever branch chose
        the pitch (guarded pick, leap recovery, contraction)."""
        t = self.bar_start + slot * GRID
        bass = self.bass_at(t)
        if bass is not None:
            self.prev2 = self.prev
            self.prev = (t, pitch, bass)

    def clean_replacement(self, slot: int, pitch: int) -> bool:
        """Would REPLACING the just-observed pick at `slot` with `pitch` keep
        the frame clean? Judged against the pair before that observation
        (prev2) — the introduce-tail nudge swaps the final note after _place
        already observed it, so the current pair is the note being replaced."""
        t = self.bar_start + slot * GRID
        bass = self.bass_at(t)
        if bass is None or self.prev2 is None or t - self.prev2[0] > self.bar_len + 1e-9:
            return True
        prev_m, prev_b = self.prev2[1], self.prev2[2]
        return not (forbidden_parallel(prev_b, prev_m, bass, pitch)
                    or (slot == 0 and forbidden_direct(prev_b, prev_m, bass, pitch)))

    def recovery_collides(self, slot: int, rec_pitch: int) -> bool:
        """Would a forced leap-recovery note at `slot` land a forbidden perfect?
        The recovery pitch is fully determined (one opposite diatonic step), so
        the collision is checkable BEFORE committing the leap that forces it."""
        t = self.bar_start + slot * GRID
        bass, pair = self.bass_at(t), self._pair(t)
        if bass is None or pair is None:
            return False
        prev_m, prev_b = pair
        return (forbidden_parallel(prev_b, prev_m, bass, rec_pitch)
                or (slot == 0 and forbidden_direct(prev_b, prev_m, bass, rec_pitch)))


# Metric accenting is owned by the Accent modifier (M4); the generator emits
# musical emphasis only (cadence targets etc.) around velocity_center.
_snap_to_scale = snap_to_scale
_diatonic_shift = diatonic_shift

DOUBLING_VELOCITY = -8  # C1: the doubled line sits under the surface dynamically too


def _double_line(events: list[NoteEvent], ctx: HarmonicContext, meter: Meter) -> list[NoteEvent]:
    """C1 parallel doubling (REFINEMENT_PLAN): a companion a diatonic 3rd below
    each melody note, switching to a 6th where the 3rd is not a chord tone on a
    strong slot — the cheapest polyphony there is, heard as richness rather
    than a second voice, so it stays inside the melody layer at lower velocity.
    A note whose double fits neither interval legally goes undoubled (the
    cadence bar's appoggiatura lean stays solo); weak slots take the 3rd, which
    is a melodic-scale member by construction."""
    mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
    strong = set(meter.strong_slots())
    doubles: list[NoteEvent] = []
    for e in events:
        # interval arithmetic, not scale walking: the source note may itself be
        # chromatic (a chord tone of an applied dominant), and diatonic_shift
        # would snap it first — landing the "3rd" a 5th below the real source
        thirds, sixths = (e.pitch - 3, e.pitch - 4), (e.pitch - 8, e.pitch - 9)
        third = next((p for p in thirds if mscale.contains(p)), None)
        sixth = next((p for p in sixths if mscale.contains(p)), None)
        if meter.slot_of(e.start) in strong:
            cands = [p for p in (third, sixth) if p is not None and p % 12 in ctx.chord_pcs]
            if not cands:  # chromatic chords: any chord-member 3rd/6th will do
                cands = [p for p in (*thirds, *sixths) if p % 12 in ctx.chord_pcs]
            pitch = cands[0] if cands else None
        else:
            pitch = third if third is not None else \
                next((p for p in thirds if p % 12 in ctx.chord_pcs), None)
        if pitch is None:
            continue
        doubles.append(NoteEvent(
            e.start, e.dur, pitch, max(1, e.velocity + DOUBLING_VELOCITY), "melody",
            degree=ctx.scale.degree_of(pitch), chord=ctx.chord_sym, role="doubling"))
    return doubles


def _velocity(params: MusicalParams, emphasis: int = 0) -> int:
    return max(1, min(127, params.velocity_center + emphasis))


def _place(cell, ctx, mscale, params, state, lo, hi, strong, peak: int | None = None,
           guard: _OuterGuard | None = None):
    """Constraint-first placement of a rhythm+contour cell: strong beats snap to
    chord tones, weak beats step, leaps recover, the register folds toward center.
    Returns (placed, anchor). This is the disposable/disguised realization —
    signature statements go through realize_faithful instead. With `peak` (A4),
    the cell's highest contour note is lifted to the nearest chord tone of the
    planned apex; a leap into it recovers by the standard opposite step — gap-fill.
    With `guard` (A3), strong-slot chord-tone picks avoid consecutive/direct
    perfects against the realized bass, and every strong onset updates the pair."""
    anchor_target = state.prev_pitch if state.prev_pitch is not None else params.register_center
    anchor_target = min(max(anchor_target, lo + 3), hi - 3)
    anchor = _nearest_pc_pitch(ctx.chord_pcs, anchor_target, lo, hi)
    placed: list[tuple[int, int, int]] = []  # (slot, dur_slots, pitch)
    prev = state.prev_pitch
    recovery = 0  # forced step direction after a leap, else 0
    last_index = len(cell.rhythm) - 1
    peak_i = -1
    if peak is not None and len(cell.contour) > 1:
        peak_i = max(range(len(cell.contour)), key=lambda i: cell.contour[i])
        if peak_i == last_index:
            peak_i = -1  # the final-note leap contraction below would undo it
    def snap(target: int, slot: int) -> int:
        if guard is not None and slot in strong:
            return guard.pick(ctx.chord_pcs, target, lo, hi, slot)
        return _nearest_pc_pitch(ctx.chord_pcs, target, lo, hi)

    for i, ((slot, dur_slots), offset) in enumerate(zip(cell.rhythm, cell.contour)):
        if i == peak_i and not (recovery and prev is not None):
            pitch = snap(peak, slot)
        elif recovery and prev is not None:
            # A leap must resolve by an opposite step — even on a strong slot
            # (an appoggiatura-style resolution; the ratio rule has slack).
            pitch = _diatonic_shift(mscale, prev, recovery)
        else:
            target = _diatonic_shift(mscale, anchor, offset)
            if slot in strong:
                pitch = snap(target, slot)
            else:
                pitch = _snap_to_scale(mscale, min(max(target, lo), hi))
                if prev is not None and abs(pitch - prev) > 5:
                    # a chord tone may absorb a moderate leap; under the A3 guard
                    # it still may not plunge past a 6th (a 10+-semitone mid-bar
                    # drop is a procedural tell) nor force a recovery step that
                    # would land a forbidden perfect on the next strong slot —
                    # the recovery pitch is determined, so look one step ahead
                    step_instead = pitch % 12 not in ctx.chord_pcs or (
                        guard is not None and abs(pitch - prev) > 9)
                    if not step_instead and guard is not None and i + 1 < len(cell.rhythm):
                        nslot = cell.rhythm[i + 1][0]
                        rec = _diatonic_shift(mscale, pitch, -1 if pitch > prev else 1)
                        step_instead = nslot in strong and guard.recovery_collides(nslot, rec)
                    if step_instead:
                        pitch = _diatonic_shift(mscale, prev, 1 if pitch > prev else -1)
        if guard is not None and not lo <= pitch <= hi:
            # under the guard, re-enter the window by stepping to its nearest
            # scale tone instead of folding an octave: the fold manufactures a
            # plunge the leap checks never saw, whose forced recovery then
            # lands on the next strong slot unguarded
            edge, step = (hi, -1) if pitch > hi else (lo, 1)
            pitch = edge
            while not mscale.contains(pitch):
                pitch += step
        while pitch > hi:
            pitch -= 12
        while pitch < lo:
            pitch += 12
        if i == last_index and prev is not None and abs(pitch - prev) > 5:
            # Bars never end mid-leap: the next bar's recovery cannot be
            # guaranteed (anchors move), so contract the final leap to a step.
            pitch = _diatonic_shift(mscale, prev, 1 if pitch > prev else -1)
        interval = 0 if prev is None else pitch - prev
        recovery = 0 if abs(interval) <= 5 else (-1 if interval > 0 else 1)
        placed.append((slot, dur_slots, pitch))
        if guard is not None and slot in strong:
            guard.observe(slot, pitch)  # whatever branch chose it
        prev = pitch
    return placed, anchor


def _introduce(motif, ctx, mscale, params, state, lo, hi, strong,
               guard: _OuterGuard | None = None):
    """Fragmentary introduction (§5.5, M15): a truncated cell that ends on an
    unstable degree (2̂ or 7̂) — the motif glimpsed and left hanging, so the later
    completed statement reads as an arrival. Realized in disguise (constraint-first)."""
    k = max(1, (len(motif.rhythm) + 1) // 2)  # the first half — a fragment
    frag = Motif(motif.rhythm[:k], motif.contour[:k], motif.shape)
    placed, anchor = _place(frag, ctx, mscale, params, state, lo, hi, strong, guard=guard)
    if placed:  # nudge the final note to the nearest 2̂/7̂ — the unresolved, hanging tail
        slot, dur, last = placed[-1]
        prev = placed[-2][2] if len(placed) > 1 else \
            (state.prev_pitch if state.prev_pitch is not None else last)
        prev2 = placed[-3][2] if len(placed) > 2 else state.prev_pitch
        unstable_pcs = (ctx.scale.pitch_at(2, 4) % 12, ctx.scale.pitch_at(7, 4) % 12)
        cands = [p for pc in set(unstable_pcs) for p in range(lo + (pc - lo) % 12, hi + 1, 12)]
        # The tail must hang, not break the line: if _place leapt into the
        # penultimate note, its final note IS that leap's recovery, so the nudge
        # may only land an unstable pitch that recovers too (an opposite step) —
        # otherwise it stands down. Elsewhere it just may not leap from prev.
        if prev2 is not None and abs(prev - prev2) > 5:
            direction = -1 if prev > prev2 else 1
            pool = [p for p in cands if 1 <= (p - prev) * direction <= 2]
        else:
            # without the guard the tail may reach any unstable instance; in
            # A3 craft mode a leap onto the hanging tone must not go
            # unrecovered (nothing recovers it — hanging is the point), so the
            # nudge stands down when no near instance exists
            pool = [p for p in cands if abs(p - prev) <= 5] or ([] if guard is not None else cands)
        if pool and guard is not None and slot in strong:
            # the nudge REPLACES the guarded pick — it must hold the same frame
            # (judged against the pair before that pick's observation)
            pool = [p for p in pool if guard.clean_replacement(slot, p)]
        if pool:
            placed[-1] = (slot, dur, min(pool, key=lambda p: (abs(p - last), p)))
            if guard is not None and slot in strong:
                guard.observe(slot, placed[-1][2])  # the nudge replaces the observed pick
    return placed, anchor, "introduced"


# --- bar generation ----------------------------------------------------------

def generate_melody(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    pos: PhrasePos,
    motif: Motif,
    state: MelodyState,
    cfg: MelodyConfig,
    rng: random.Random,
    lifecycle: str = "",
    signature: Motif | None = None,
    apex: ApexPlan | None = None,
    bass: list[NoteEvent] | None = None,
    replay: tuple[tuple[int, int, int], ...] | None = None,
    double: bool = False,
    prev_bass: int | None = None,
) -> tuple[list[NoteEvent], MelodyState, str]:
    """One bar of melody. `lifecycle` stages the persistent `signature` (M15/M17)
    *positionally* within the phrase — the phrase keeps its own disposable `motif`,
    and the signature lands as an event within it, not as wallpaper:

    - "" — plain sentence form on `motif` (byte-identical to the disposable path).
    - "introduced" / "developed" — one signature event at the continuation onset
      (pos == bars//2): a fragmentary glimpse ending unstably, or the full cell in
      disguise (constraint-first). Every other bar: sentence form on `motif`.
    - "stated" — as above, but the event is the faithful recurrence of an authored
      signature (M17 secondary colour).
    - "completed" — the payoff: sentence form develops the *signature*, driving
      into a faithful statement fused with the cadence bar (the arrival IS the
      statement); the drive never rests."""
    lo = params.register_center - cfg.range_semitones
    hi = params.register_center + cfg.range_semitones
    if lifecycle == "completed":
        apex = None  # the cadence-fused statement owns the phrase's shape (A4 stands down)
    apex_bar = apex is not None and pos.pos == apex.pos
    if apex is not None:
        # single peak: the apex bar itself tops out AT the plan (so the peak
        # note is the bar's ceiling, not a waypoint on the way past it) and
        # every other bar stays below it — floored so the window never
        # collapses past the dramaturg's own minimum range
        hi = max(min(hi, apex.pitch - (0 if apex_bar else 1)), lo + 6)
    sig = signature if signature is not None else motif
    sig_event = lifecycle in ("introduced", "developed", "stated") and pos.pos == pos.bars // 2

    # A3 outer-voice guard: active when the frame exists (a realized bass) and
    # the config asks for it. Signature realizations stay unguarded — their
    # identity is licensed as a whole (M15) — but their pair still expires.
    guard = None
    if cfg.counterpoint and bass:
        guard = _OuterGuard(bass, ctx.bar * meter.bar_quarters, meter.bar_quarters,
                            state.prev_outer, prev_root=prev_bass)

    if pos.slot == "cadence" and ctx.cadence_policy:
        events, new_state, trace = (
            _cadence_statement(sig, ctx, meter, params, state, lo, hi)
            if lifecycle == "completed"
            else _cadence_bar(ctx, meter, params, state, lo, hi, rng, guard))
        if double and events:
            dbl = _double_line(events, ctx, meter)
            events += dbl
            trace += f" │ doubled {len(dbl)}"
        return events, new_state, trace

    rest_prob = max(0.0, cfg.bar_rest_max - params.note_density * 0.4)
    if (lifecycle != "completed" and not sig_event and not apex_bar and pos.slot == "free"
            and rng.random() < rest_prob):
        return [], state, "melody: rest bar"  # signature events, the payoff drive, and the apex never rest

    mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
    strong = set(meter.strong_slots())
    faithful = False

    # B2 period answer: the consequent opens with the antecedent's realized
    # bar verbatim (the conductor sends `replay` only when harmony and scale
    # match). Stand down if the window moved under it or the entry pair would
    # break the outer-voice frame — the aliased motif then answers in rhythm.
    replayed = False
    if replay and lifecycle != "completed":
        ok = all(lo <= p <= hi for _, _, p in replay)
        if ok and state.prev_pitch is not None:
            # the answer enters from the half-cadence target, not from wherever
            # the antecedent entered: a leap in must be recovered by the replay
            # itself or the aliased motif answers in rhythm instead
            entry_iv = replay[0][2] - state.prev_pitch
            if abs(entry_iv) > 5:
                back = replay[1][2] - replay[0][2] if len(replay) > 1 else 0
                ok = back != 0 and (back > 0) != (entry_iv > 0) and abs(back) <= 2
        if ok and guard is not None:
            # walk the outer-voice frame across the WHOLE replay, not just its
            # entry: the answer plays over a freshly realized bass whose fifths
            # and approach tones sit under different replay notes than they did
            # under the antecedent's
            pair = guard.prev
            for s, _, p in replay:
                if s not in strong:
                    continue
                t = ctx.bar * meter.bar_quarters + s * GRID
                bass_now = guard.bass_at(t)
                if bass_now is None:
                    continue
                if pair is not None and t - pair[0] <= meter.bar_quarters + 1e-9:
                    prev_m, prev_b = pair[1], pair[2]
                    if (forbidden_parallel(prev_b, prev_m, bass_now, p)
                            or (s == 0 and forbidden_direct(prev_b, prev_m, bass_now, p))):
                        ok = False
                        break
                pair = (t, p, bass_now)
        if ok:
            placed, anchor = list(replay), replay[0][2]
            op, shape, replayed = "period answer", "verbatim", True
            if guard is not None:
                for slot, _, p in placed:
                    if slot in strong:
                        guard.observe(slot, p)

    if replayed:
        pass
    elif lifecycle == "completed":
        # Payoff drive (§5.5, M15): the phrase develops the signature itself,
        # constraint-first — bending to the harmony — so the faithful cadential
        # statement lands as the destination, not as the seventh repetition.
        variant, base_op = phrase_variant(sig, pos.pos, rng, meter.slots)
        placed, anchor = _place(variant, ctx, mscale, params, state, lo, hi, strong,
                                guard=guard)
        op, shape = f"drive {base_op}", sig.shape
    elif sig_event and lifecycle == "introduced":
        placed, anchor, op = _introduce(sig, ctx, mscale, params, state, lo, hi, strong,
                                        guard=guard)
        shape = sig.shape
    elif sig_event and lifecycle == "developed":
        placed, anchor = _place(sig, ctx, mscale, params, state, lo, hi, strong,
                                guard=guard)
        op, shape = "signature disguised", sig.shape
    elif sig_event:  # "stated": the faithful recurrence of an authored signature (M17)
        placed = realize_faithful(sig, mscale, ctx.chord_pcs, lo, hi, strong, near=state.prev_pitch)
        anchor = placed[0][2] if placed else params.register_center
        op, shape, faithful = "signature faithful", sig.shape, True
    else:
        variant, op = phrase_variant(motif, pos.pos, rng, meter.slots)
        placed, anchor = _place(variant, ctx, mscale, params, state, lo, hi, strong,
                                peak=apex.pitch if apex_bar else None, guard=guard)
        if apex_bar:
            op += "+apex"
        shape = motif.shape

    bar_start = ctx.bar * meter.bar_quarters
    events: list[NoteEvent] = []
    for i, (slot, dur_slots, pitch) in enumerate(placed):
        if faithful:
            # a faithful signature statement is licensed as a whole — its
            # intervals are the identity (verified by recognizability), so the
            # note-level melodic heuristics do not apply (see verify._lint_melody).
            role = "motif"
        elif pitch % 12 in ctx.chord_pcs:
            role = "chord-tone"
        elif ctx.scale.contains(pitch):
            prev_p = placed[i - 1][2] if i else None
            next_p = placed[i + 1][2] if i + 1 < len(placed) else None
            role = "neighbor" if prev_p is not None and next_p == prev_p else "passing"
        else:
            role = "borrowed"
        events.append(NoteEvent(
            bar_start + slot * GRID, dur_slots * GRID, pitch, _velocity(params),
            "melody", degree=ctx.scale.degree_of(pitch), chord=ctx.chord_sym, role=role,
        ))

    doubled = ""
    if double and events:
        dbl = _double_line(events, ctx, meter)
        events += dbl
        doubled = f" │ doubled {len(dbl)}"

    new_state = MelodyState(prev_pitch=placed[-1][2] if placed else state.prev_pitch,
                            prev_anchor=anchor,
                            prev_outer=guard.prev if guard is not None else state.prev_outer)
    return events, new_state, f"melody: {op} ({shape}) anchor {pitch_name(anchor)} n={len(placed)}{doubled}"


def _cadence_target_pcs(ctx: HarmonicContext) -> tuple[int, ...]:
    """Policy-appropriate cadence-target pitch classes, filtered to chord members
    (fallback to the chord itself, e.g. a borrowed bVI)."""
    degree_pcs = tuple(
        ctx.scale.pitch_at(d, 4) % 12
        for d in CADENCE_TARGET_DEGREES[ctx.cadence_policy]
        if ctx.scale.pitch_at(d, 4) % 12 in ctx.chord_pcs
    )
    return degree_pcs or tuple(ctx.chord_pcs)


def _cadence_statement(
    motif: Motif,
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    state: MelodyState,
    lo: int,
    hi: int,
) -> tuple[list[NoteEvent], MelodyState, str]:
    """The completed signature fused with the cadence (§5.5, M15): the whole cell,
    contour intact, transposed so its final note IS the cadence target, held to the
    bar end under a crescendo — the payoff states the signature at the arrival,
    a flourish that resolves, instead of a generic two-note approach after a phrase
    of noodling. Licensed as a whole (role "motif")."""
    placed = realize_cadential(motif, ctx.scale, _cadence_target_pcs(ctx), lo, hi,
                               near=state.prev_pitch, slots=meter.slots)
    bar_start = ctx.bar * meter.bar_quarters
    n = len(placed)
    events = [
        NoteEvent(
            bar_start + slot * GRID, dur * GRID, pitch,
            _velocity(params, -2 + round(8 * i / (n - 1)) if n > 1 else 6),
            "melody", degree=ctx.scale.degree_of(pitch), chord=ctx.chord_sym, role="motif",
        )
        for i, (slot, dur, pitch) in enumerate(placed)
    ]
    target = placed[-1][2]
    new_state = MelodyState(prev_pitch=target, prev_anchor=target,
                            prev_outer=state.prev_outer)
    names = " -> ".join(pitch_name(e.pitch) for e in events)
    return events, new_state, f"melody: cadence statement ({ctx.cadence_policy}) {names}"


def _cadence_bar(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    state: MelodyState,
    lo: int,
    hi: int,
    rng: random.Random,
    guard: _OuterGuard | None = None,
) -> tuple[list[NoteEvent], MelodyState, str]:
    """Approach + held target: an appoggiatura-style formula converging on a
    chord tone appropriate to the cadence policy (tendency-tone resolution).
    With the A3 guard, the approach direction runs contrary to the bass's
    arrival — the frame's classic close: outer voices converge or diverge
    into the cadence, never chase."""
    scale = ctx.scale
    candidate_pcs = _cadence_target_pcs(ctx)
    center = state.prev_pitch if state.prev_pitch is not None else params.register_center
    if guard is not None:
        # the window may have moved under the line (apex cap, register shift);
        # re-enter at the edge instead of stepping from an out-of-range pitch
        center = min(max(center, lo), hi)

    # Walk from where the line is toward the cadence target: a step first,
    # then re-anchor the target nearby, bridging any remaining gap with one
    # passing tone. Guarantees a leap-free, gap-fill-style resolution even
    # when the previous phrase ended at a register extreme.
    provisional = _nearest_pc_pitch(candidate_pcs, center, lo, hi)
    direction = 1 if provisional > center else -1
    if guard is not None and state.prev_pitch is not None:
        bass_now = guard.bass_at(guard.bar_start)
        b_prev = guard.prev_root
        if b_prev is None:  # direct callers without the conductor's thread
            pair = guard._pair(guard.bar_start)
            b_prev = pair[1] if pair is not None else None
        if bass_now is not None and b_prev is not None and bass_now != b_prev:
            # step contrary to the bass's root arrival, downbeat to downbeat —
            # lint_outer's own yardstick (the last strong pair may sit on a
            # fifth or an approach tone, whose direction says nothing about
            # the harmonic arrival)
            direction = -1 if bass_now > b_prev else 1
    first = _diatonic_shift(scale, center, direction) if state.prev_pitch is not None else \
        _diatonic_shift(scale, provisional, -direction)
    first = min(max(first, lo), hi)
    if guard is not None:
        if not scale.contains(first):  # the range clamp may land off-scale
            first = snap_to_scale(scale, first)
            if first > hi:
                first = _diatonic_shift(scale, first, -1)
        bass_now = guard.bass_at(guard.bar_start)
        pair = guard._pair(guard.bar_start)
        if bass_now is not None and pair is not None:
            prev_m, prev_b = pair
            def _clean(p: int) -> bool:
                return not (forbidden_parallel(prev_b, prev_m, bass_now, p)
                            or forbidden_direct(prev_b, prev_m, bass_now, p))
            if not _clean(first):  # step to the nearest scale tone that opens cleanly
                cands = sorted((p for p in range(lo, hi + 1) if scale.contains(p)),
                               key=lambda p: (abs(p - first), p))
                first = next((p for p in cands if _clean(p)), first)
    target = _nearest_pc_pitch(candidate_pcs, first, lo, hi)
    if guard is not None and state.prev_pitch is not None and abs(first - state.prev_pitch) > 5:
        # the window moved under the line (register contraction, apex cap) and
        # the entry is a leap: run toward a target on the opposite side, so the
        # walk itself is the recovery instead of continuing the plunge
        entry = 1 if first > state.prev_pitch else -1
        opposite = [p for p in _pc_candidates(candidate_pcs, first, lo, hi)
                    if (p - first) * entry < 0]
        if opposite:
            target = opposite[0]
    if target == first:
        target = _nearest_pc_pitch(candidate_pcs, first + direction * 2, lo, hi)

    bar_start = ctx.bar * meter.bar_quarters
    eighth, quarter = 2 * GRID, 4 * GRID

    def role_of(p: int) -> str:
        if p % 12 in ctx.chord_pcs:
            return "chord-tone"
        return "appoggiatura" if scale.contains(p) else "borrowed"

    def note(t: float, d: float, p: int, emphasis: int, role: str | None = None) -> NoteEvent:
        return NoteEvent(t, d, p, _velocity(params, emphasis), "melody",
                         degree=scale.degree_of(p), chord=ctx.chord_sym, role=role or role_of(p))

    # Scalar run toward the target: every hop is a diatonic step, so the
    # resolution is leap-free no matter how far the phrase ended from it.
    run: list[int] = []
    p = first
    while abs(target - p) > 2 and len(run) < 4:
        p = _diatonic_shift(scale, p, 1 if target > p else -1)
        if p == target:
            break
        run.append(p)

    if run:
        events = [note(bar_start, eighth, first, -2)]
        for i, pitch in enumerate(run):
            events.append(note(bar_start + (i + 1) * eighth, eighth, pitch, -6,
                               role="passing" if role_of(pitch) == "appoggiatura" else None))
        target_start = bar_start + (len(run) + 1) * eighth
    else:
        events = [note(bar_start, quarter, first, -2)]
        target_start = bar_start + quarter
    events.append(note(target_start, ctx.bar * meter.bar_quarters + meter.bar_quarters - target_start,
                       target, 6))

    if guard is not None:
        strong = set(meter.strong_slots())
        for e in events:  # chronological: first, run..., target
            slot = meter.slot_of(e.start)
            if slot in strong:
                guard.observe(slot, e.pitch)
    new_state = MelodyState(prev_pitch=target, prev_anchor=target,
                            prev_outer=guard.prev if guard is not None else state.prev_outer)
    names = " -> ".join(pitch_name(e.pitch) for e in events)
    return events, new_state, f"melody: cadence ({ctx.cadence_policy}) {names}"
