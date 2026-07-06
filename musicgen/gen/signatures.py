"""Authored signature motifs (PLANS.md §5.5, M17): a curated library of
hand-authored cells the generation loop states when appropriate, so identities
recur — the counterpart to the disposable §5.5 phrase motif and the single
generated signature of M15.

Each entry carries an **importance** (a landmark hero theme vs. secondary colour),
re-weightable per scene. At every phrase boundary the `MotifDirector` weighs a
ticking **overdue × importance** pressure against the **theory-appropriateness** of
the upcoming harmony (the best-fitting admissible transform — inversion,
displacement, truncation), with a **leniency** knob trading recurrence frequency
against fit. A selected landmark lands via M15's faithful realization (and, later,
spends the M13 ledger with M14's cadential dissonance). Deterministic: the decision
is a pure function of (bars-since state, importance, context, leniency).

Layering: this sits above melody.py (transforms) and motif.py (realize/fit), so
there is no import cycle. Nothing wires it into the engine yet — an empty library
is byte-identical; the conductor hook comes next (M17.2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from musicgen.gen.melody import Motif, admissible_transforms
from musicgen.gen.motif import motif_fit
from musicgen.theory.scales import Scale

# Selection constants. Overdue pressure = bars×importance, saturating to 1.0 at
# _OVERDUE_SCALE; the launch score is pressure × fit, gated by a threshold the
# leniency knob lowers from strict to lenient. Strict → launches only when a motif
# is both overdue and well-fitting (rare, high fit); lenient → launches on moderate
# pressure or fit (frequent, lower fit) — the recurrence-vs-fit trade the DoD wants.
_OVERDUE_SCALE = 16.0
_THRESH_STRICT, _THRESH_LENIENT = 0.55, 0.15
_FIT_MIN = 0.34  # a request must still land at least this cleanly
_NEVER = 999     # bars-since for a motif not yet stated — maximally overdue


@dataclass(frozen=True)
class SignatureMotif:
    tag: str                 # "hero", "threat", … — the game's handle for meaning
    motif: Motif             # the authored cell (rhythm + contour + shape)
    importance: float = 0.5  # 0..1: identity landmark (high) vs secondary colour (low)


@dataclass
class MotifDirector:
    """Selects authored signatures to state, tracking bars since each was last heard.
    Lives in ConductorState; state ages one phrase at a time."""
    library: tuple[SignatureMotif, ...] = ()
    bars_since: dict[str, int] = field(default_factory=dict)
    last: str = ""  # trace of the most recent decision

    def age(self, bars: int) -> None:
        """A phrase passed; every signature grows more overdue."""
        for tag in self.bars_since:
            self.bars_since[tag] += bars

    def observe(self, tag: str, bars: int) -> None:
        """Record that `tag` was just stated: age the rest, reset its clock."""
        self.age(bars)
        self.bars_since[tag] = 0

    def _best_transform(self, sig, scale, chord_pcs, lo, hi, strong_slots, near):
        best = None
        for name, m in admissible_transforms(sig.motif):
            fit = motif_fit(m, scale, chord_pcs, lo, hi, strong_slots, near=near)
            if best is None or fit > best[0]:
                best = (fit, name, m)
        return best  # (fit, transform_name, transformed_motif)

    def select(self, scale: Scale, chord_pcs, lo, hi, strong_slots,
               leniency: float, near: int | None = None, requested: str = ""):
        """Pick a signature to state this phrase, or None. Overdue×importance is the
        pressure; the best-fitting transform (measured from `near`, the line's current
        pitch) is the gate; leniency lowers the fit bar (more recurrence, lower fit). A
        `requested` tag (the game's request_motif) wins outright once it fits at all —
        the game's authored intent overrides the overdue calculus. Deterministic."""
        threshold = _THRESH_STRICT - leniency * (_THRESH_STRICT - _THRESH_LENIENT)
        best = None
        for sig in self.library:
            overdue = self.bars_since.get(sig.tag, _NEVER) * sig.importance
            pressure = min(1.0, overdue / _OVERDUE_SCALE)
            fit, transform, motif_t = self._best_transform(sig, scale, chord_pcs, lo, hi, strong_slots, near)
            forced = requested == sig.tag
            # a request forces the tag once it lands cleanly at all; otherwise the
            # overdue×fit score must clear the leniency threshold.
            if not ((forced and fit >= _FIT_MIN) or (not forced and pressure * fit >= threshold)):
                continue
            rank = (1e6 + fit) if forced else pressure * fit  # a request outranks any pressure
            if best is None or rank > best[0]:
                best = (rank, sig, transform, motif_t, fit)
        if best is None:
            self.last = "signature: none appropriate"
            return None
        _, sig, transform, motif_t, fit = best
        self.last = f"signature '{sig.tag}' via {transform} (fit {fit:.2f})"
        return sig, transform, motif_t


# A small example library for demos and tests — the game supplies its own. A
# landmark hero theme (recurs often) and a secondary threat colour (sparser).
HERO = SignatureMotif("hero", Motif(((0, 4), (4, 2), (6, 2), (8, 4)), (0, 2, 1, 0), "arch"), importance=0.9)
THREAT = SignatureMotif("threat", Motif(((0, 2), (2, 2), (4, 4)), (0, -1, -2), "descent"), importance=0.5)
EXAMPLE_LIBRARY = (HERO, THREAT)
