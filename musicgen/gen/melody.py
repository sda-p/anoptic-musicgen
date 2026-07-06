"""Motif-based melody engine (PLANS.md §5.5).

Each phrase owns one Motif (a rhythm cell from the roughness engine plus a
contour realized as diatonic offsets). Bars realize sentence-form variants of
it — statement, sequence, development ops, an ornamented pre-cadence drive,
and a cadence formula that converges on a policy-appropriate target degree.

Pitch selection is constraint-first, never a free walk: strong beats snap to
chord tones, weak beats move by scale steps, leaps beyond a P4 recover by an
opposite step, and the register window folds pitches back toward center.
Over borrowed chords the melodic scale follows the chord's source mode; such
tones are labeled "borrowed" for the linter and the dump.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from musicgen.gen.motif import realize_faithful
from musicgen.gen.rhythm import rough_cell
from musicgen.gen.structure import PhrasePos
from musicgen.ir import GRID, HarmonicContext, Meter, MusicalParams, NoteEvent
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


@dataclass(frozen=True)
class Motif:
    rhythm: tuple[tuple[int, int], ...]  # (slot, dur_slots) within one bar
    contour: tuple[int, ...]             # diatonic offsets from the bar anchor
    shape: str


@dataclass
class MelodyState:
    prev_pitch: int | None = None
    prev_anchor: int | None = None


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

def _nearest_pc_pitch(pcs, target: int, lo: int, hi: int) -> int:
    best: int | None = None
    for pc in set(pcs):
        first = lo + (pc - lo) % 12
        for p in range(first, hi + 1, 12):
            if best is None or (abs(p - target), p) < (abs(best - target), best):
                best = p
    return best if best is not None else target


# Metric accenting is owned by the Accent modifier (M4); the generator emits
# musical emphasis only (cadence targets etc.) around velocity_center.
_snap_to_scale = snap_to_scale
_diatonic_shift = diatonic_shift


def _velocity(params: MusicalParams, emphasis: int = 0) -> int:
    return max(1, min(127, params.velocity_center + emphasis))


def _place(cell, ctx, mscale, params, state, lo, hi, strong):
    """Constraint-first placement of a rhythm+contour cell: strong beats snap to
    chord tones, weak beats step, leaps recover, the register folds toward center.
    Returns (placed, anchor). This is the disposable/disguised realization —
    signature statements go through realize_faithful instead."""
    anchor_target = state.prev_pitch if state.prev_pitch is not None else params.register_center
    anchor_target = min(max(anchor_target, lo + 3), hi - 3)
    anchor = _nearest_pc_pitch(ctx.chord_pcs, anchor_target, lo, hi)
    placed: list[tuple[int, int, int]] = []  # (slot, dur_slots, pitch)
    prev = state.prev_pitch
    recovery = 0  # forced step direction after a leap, else 0
    last_index = len(cell.rhythm) - 1
    for i, ((slot, dur_slots), offset) in enumerate(zip(cell.rhythm, cell.contour)):
        if recovery and prev is not None:
            # A leap must resolve by an opposite step — even on a strong slot
            # (an appoggiatura-style resolution; the ratio rule has slack).
            pitch = _diatonic_shift(mscale, prev, recovery)
        else:
            target = _diatonic_shift(mscale, anchor, offset)
            if slot in strong:
                pitch = _nearest_pc_pitch(ctx.chord_pcs, target, lo, hi)
            else:
                pitch = _snap_to_scale(mscale, min(max(target, lo), hi))
                if prev is not None and abs(pitch - prev) > 5 and pitch % 12 not in ctx.chord_pcs:
                    pitch = _diatonic_shift(mscale, prev, 1 if pitch > prev else -1)
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
        prev = pitch
    return placed, anchor


def _introduce(motif, ctx, mscale, params, state, lo, hi, strong):
    """Fragmentary introduction (§5.5, M15): a truncated cell that ends on an
    unstable degree (2̂ or 7̂) — the motif glimpsed and left hanging, so the later
    completed statement reads as an arrival. Realized in disguise (constraint-first)."""
    k = max(1, (len(motif.rhythm) + 1) // 2)  # the first half — a fragment
    frag = Motif(motif.rhythm[:k], motif.contour[:k], motif.shape)
    placed, anchor = _place(frag, ctx, mscale, params, state, lo, hi, strong)
    if placed:  # nudge the final note to the nearest 2̂/7̂ — the unresolved, hanging tail
        slot, dur, last = placed[-1]
        unstable_pcs = (ctx.scale.pitch_at(2, 4) % 12, ctx.scale.pitch_at(7, 4) % 12)
        placed[-1] = (slot, dur, _nearest_pc_pitch(unstable_pcs, last, lo, hi))
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
) -> tuple[list[NoteEvent], MelodyState, str]:
    """One bar of melody. `lifecycle` selects the motif realization (M15):
    "completed" — the faithful signature statement; "introduced" — a fragmentary
    glimpse ending unstably; "developed"/"" — the disguised constraint-first
    development (byte-identical to the disposable path when "")."""
    lo = params.register_center - cfg.range_semitones
    hi = params.register_center + cfg.range_semitones
    faithful = lifecycle == "completed"

    if pos.slot == "cadence" and ctx.cadence_policy:
        return _cadence_bar(ctx, meter, params, state, lo, hi, rng)

    rest_prob = max(0.0, cfg.bar_rest_max - params.note_density * 0.4)
    if not faithful and pos.slot == "free" and rng.random() < rest_prob:
        return [], state, "melody: rest bar"  # a completed statement never rests

    mscale = ctx.chord.scale_for(ctx.scale) if ctx.chord else ctx.scale
    strong = set(meter.strong_slots())

    if faithful:
        # Signature-faithful realization (§5.5, M15): the whole cell transposed to
        # fit, contour intact — the completed statement the ear recognizes. It
        # connects to the previous pitch so successive statements don't leap.
        placed = realize_faithful(motif, mscale, ctx.chord_pcs, lo, hi, strong, near=state.prev_pitch)
        anchor, op = (placed[0][2] if placed else params.register_center), "faithful"
    elif lifecycle == "introduced":
        placed, anchor, op = _introduce(motif, ctx, mscale, params, state, lo, hi, strong)
    else:
        variant, op = phrase_variant(motif, pos.pos, rng, meter.slots)
        placed, anchor = _place(variant, ctx, mscale, params, state, lo, hi, strong)

    bar_start = ctx.bar * meter.bar_quarters
    events: list[NoteEvent] = []
    for i, (slot, dur_slots, pitch) in enumerate(placed):
        if faithful:
            # a completed signature statement is licensed as a whole — its
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

    new_state = MelodyState(prev_pitch=placed[-1][2] if placed else state.prev_pitch, prev_anchor=anchor)
    return events, new_state, f"melody: {op} ({motif.shape}) anchor {pitch_name(anchor)} n={len(placed)}"


def _cadence_bar(
    ctx: HarmonicContext,
    meter: Meter,
    params: MusicalParams,
    state: MelodyState,
    lo: int,
    hi: int,
    rng: random.Random,
) -> tuple[list[NoteEvent], MelodyState, str]:
    """Approach + held target: an appoggiatura-style formula converging on a
    chord tone appropriate to the cadence policy (tendency-tone resolution)."""
    scale = ctx.scale
    degree_pcs = tuple(
        scale.pitch_at(d, 4) % 12
        for d in CADENCE_TARGET_DEGREES[ctx.cadence_policy]
        if scale.pitch_at(d, 4) % 12 in ctx.chord_pcs
    )
    candidate_pcs = degree_pcs or tuple(ctx.chord_pcs)  # fallback: e.g. borrowed bVI
    center = state.prev_pitch if state.prev_pitch is not None else params.register_center

    # Walk from where the line is toward the cadence target: a step first,
    # then re-anchor the target nearby, bridging any remaining gap with one
    # passing tone. Guarantees a leap-free, gap-fill-style resolution even
    # when the previous phrase ended at a register extreme.
    provisional = _nearest_pc_pitch(candidate_pcs, center, lo, hi)
    direction = 1 if provisional > center else -1
    first = _diatonic_shift(scale, center, direction) if state.prev_pitch is not None else \
        _diatonic_shift(scale, provisional, -direction)
    first = min(max(first, lo), hi)
    target = _nearest_pc_pitch(candidate_pcs, first, lo, hi)
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

    new_state = MelodyState(prev_pitch=target, prev_anchor=target)
    names = " -> ".join(pitch_name(e.pitch) for e in events)
    return events, new_state, f"melody: cadence ({ctx.cadence_policy}) {names}"
