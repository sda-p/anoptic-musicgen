"""The dramaturg: a stateful layer between the affect stream and the memoryless
mapper that turns *accumulated* tension into *sized* payoffs (PLANS.md §5.8, M13).

The mapper is memoryless — identical levers give identical bars — so authored
long-range shape is impossible from levers alone. The dramaturg keeps a
tension-debt **ledger**: sustained high tension accrues debt by withholding
resolution (rationing the authentic cadence), and a release spends the ledger at
once, its magnitude graded by how much debt had accrued. A deceptive cadence
spends partially and rolls the rest forward — the safety valve for setup that
goes stale, or a game that never releases.

SKELETON (M13). Real and complete: the ledger, the accrue / spend / roll-forward
decision, the monotone payoff magnitude, and the trace. Wired into generation:
**cadence rationing** (the dramaturg picks each phrase's cadence — deceptive while
withholding, authentic on the spend), once withholding escalates **gate + register
withholding** (a top tier held out of the gate set and the melody's range
contracted), **mode-brightening on the spend** (a same-tonic parallel lift, graded
by the payoff); throughout the withholding a **root-position-tonic walk bias** (the
walk circles the tonic via vi/iii instead of landing on I, so the buildup is as
legible as the payoff); and an **escalation ladder** (a *sustained* hold
progressively pushes loudness / agitation / accent up — a coiled spring, not a
plateau, so a long withhold keeps building). So the spend is *heard*: the tonic
returns, the suppressed tier snaps back, the melody opens up, and the mode
brightens — all graded by how long it withheld. Still traced-only: the
voicing-inversion nuance of the tonic bias and the *structural* escalation rungs
(ostinato, step-up sequences — partly blocked on M14 pedals) — the remainder of M13.

M14 (earned dissonance, §5.8): the dramaturg also deploys *obligation-bearing*
dissonance — structural tension that must resolve, distinct from the ambient
tension-tiered colour of `_choose_extensions`. It ornaments every cadence it
controls with a prepared **suspension** (`Directive.suspend`): while withholding
these resolve into deceptive cadences (local relief, the debt stands); on the spend
one resolves into the tonic, so the payoff is itself a resolved dissonance. The pad
realizes a suspension only where a prepared voice exists, so an infeasible request
plants nothing (never a dangling obligation the linter would flag). Gated by
`DramaturgConfig.earned_dissonance` (False => M13-identical). Pedals, cadential
appoggiaturas, and secondary-dominant / modal-mixture obligations follow.

Determinism: `on_bar` mutates the ledger in place, so the ledger is a pure
function of (seed, affect trajectory, bar). With the dramaturg disabled
(EngineConfig.dramaturg is None) the conductor never touches the ledger and its
output is byte-identical to today.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from musicgen.gen.structure import PhrasePos


@dataclass(frozen=True)
class DramaturgConfig:
    """The dramaturg's tunable constants — hot-swappable live (playground-adjustable
    by ear). `leniency` is the headline knob; the rest shape the escalation/curve."""
    enabled: bool = True        # master toggle; False => inert, byte-identical to no dramaturg
    leniency: float = 0.5       # 0 strict (withholds long) .. 1 lenient (releases readily)
    accrue_above: float = 0.55  # base tension at/above which a phrase withholds
    debt_gain: float = 0.12     # payoff-curve steepness (monotone in debt regardless)
    escalate_phrases: int = 2   # phrases of sustained withholding per escalation rung
    hold_tier: str = "arp"      # layer held out of the gate set while withholding (snaps back on spend)
    register_cap_max: int = 6   # max semitones the melody range is contracted while withholding
    escalation_cap: int = 4     # rungs of sustained withholding to reach full escalation intensity
    big_spend: float = 0.7      # payoff magnitude above which the spend lifts the mode 2 steps, not 1
    max_debt: int = 96          # clamp so a runaway trajectory can't unbound the ledger
    earned_dissonance: bool = True  # M14: deploy obligation-bearing dissonance (suspensions …); False => M13-identical


@dataclass
class Ledger:
    """All dramaturg sequential state — lives in ConductorState, resets with the
    engine. Debts are non-negative accumulators; the rest tracks the derivative
    and the last decision for the trace / demo."""
    bars_since_authentic: int = 0   # primary debt: bars since the last authentic cadence
    deceptions: int = 0             # rolled-forward debt: unresolved deceptive cadences
    withholding_phrases: int = 0    # consecutive phrases accruing (drives escalation)
    peak_tension: float = 0.0       # high-water mark of the current buildup
    prev_base_tension: float | None = None
    phrase_cadence: dict[int, str] = field(default_factory=dict)  # dramaturg's per-phrase choice
    suppress_tonic: bool = False    # per-bar: walk should circle the tonic (read at chord-gen time)
    last_spend: float = 0.0         # magnitude of the most recent payoff (trace / demo readout)
    last_note: str = ""             # most recent trace line


@dataclass(frozen=True)
class Directive:
    """What the dramaturg asks of a bar. All-neutral when idle. `cadence`,
    `lock_layers`, and `register_cap` are applied by the conductor (M13);
    `withhold_root_tonic` and the escalation rung are still traced-only."""
    cadence: str | None = None          # applied: the phrase's forced cadence policy
    lock_layers: tuple[str, ...] = ()   # applied: tiers held out of the gate set while withholding
    register_cap: int = 0               # applied: semitones to contract the melody's range
    brighten: int = 0                   # applied: brightness steps to lift the mode on the spend
    intensify: float = 0.0              # applied: escalation intensity 0..1 (louder/denser while withholding)
    withhold_root_tonic: bool = False   # applied: the walk circles the tonic (voicing-inversion TBD)
    escalation: int = 0                 # the escalation rung (drives intensify; also traced)
    payoff: float = 0.0                 # >0 on a spend bar: the graded resolution magnitude
    suspend: bool = False               # applied (M14): request a prepared pad suspension this bar
    note: str = ""


def spend_magnitude(ledger: Ledger, cfg: DramaturgConfig) -> float:
    """The graded payoff: strictly increasing in accrued debt (bars withheld plus
    twice the rolled-forward deceptions), saturating in [0, 1). Monotonicity is
    the M13 acceptance property — a longer buildup can only pay off bigger for a
    fixed release gesture."""
    debt = min(ledger.bars_since_authentic + 2 * ledger.deceptions, cfg.max_debt)
    return 1.0 - 1.0 / (1.0 + cfg.debt_gain * debt)


class Dramaturg:
    """Stateless logic over a Ledger (which carries the state). One instance per
    engine, created only when EngineConfig.dramaturg is set."""

    def __init__(self, cfg: DramaturgConfig) -> None:
        self.cfg = cfg

    def _release_level(self) -> float:
        # leniency raises the tension under which the ledger releases: lenient ->
        # releases while tension is still fairly high (short buildups); strict ->
        # only once tension is genuinely low (holds out for long buildups).
        c = self.cfg
        return c.accrue_above * (0.4 + 0.6 * c.leniency)

    @staticmethod
    def _debt(ledger: Ledger) -> int:
        return ledger.bars_since_authentic + ledger.deceptions

    def on_bar(self, ledger: Ledger, base_tension: float, pos: PhrasePos) -> Directive:
        """Observe one realized bar; update the ledger; return this bar's
        directive. The accrue/spend decision is taken once per phrase, at pos 0,
        so the chosen cadence is in place before the phrase's cadence chord is
        generated (two bars ahead)."""
        ledger.prev_base_tension = base_tension

        if pos.pos != 0:
            directive = self._standing(ledger)  # mid-phrase: carry the standing withholding
        else:
            accruing = base_tension >= self.cfg.accrue_above
            releasing = base_tension < self._release_level() and self._debt(ledger) > 0
            if releasing and not accruing:
                directive = self._spend(ledger, pos)
            elif accruing:
                directive = self._accrue(ledger, pos)
            else:
                ledger.withholding_phrases = 0  # neutral zone: hand the cadence back to the mapper
                ledger.last_note = f"dramaturg: idle (tension {base_tension:.2f})"
                directive = Directive(note=ledger.last_note)
        # persist the tonic-suppression signal for the walk, which runs a bar ahead
        ledger.suppress_tonic = directive.withhold_root_tonic
        # M14 earned dissonance: ornament a cadence the dramaturg controls with a
        # prepared suspension. While withholding it resolves *into a deceptive
        # cadence* (local relief, the debt stands); on the spend it resolves *into
        # the tonic* — the payoff itself is a resolved dissonance. The pad realizes
        # it only where a prepared voice exists, so an infeasible request plants
        # nothing (and never a dangling obligation).
        if (self.cfg.earned_dissonance and pos.slot in ("pre-cadence", "cadence")
                and ledger.phrase_cadence.get(pos.phrase) is not None):
            directive = replace(directive, suspend=True)
        return directive

    def _withholding(self, ledger: Ledger) -> tuple[int, tuple[str, ...], float, int]:
        """Gate / register / escalation for the current rung: nothing at rung 0,
        then a held tier, a growing melody-range contraction, and a growing
        escalation *intensity* (louder / denser) so a long hold keeps building
        rather than plateauing. Returns (register_cap, lock_layers, intensify, rung)."""
        rung = ledger.withholding_phrases // max(1, self.cfg.escalate_phrases)
        if rung < 1:
            return 0, (), 0.0, rung
        cap = min(rung * 2, self.cfg.register_cap_max)
        intensify = min(rung / self.cfg.escalation_cap, 1.0)
        return cap, (self.cfg.hold_tier,), intensify, rung

    def _accrue(self, ledger: Ledger, pos: PhrasePos) -> Directive:
        ledger.withholding_phrases += 1
        ledger.bars_since_authentic = min(ledger.bars_since_authentic + pos.bars, self.cfg.max_debt)
        ledger.deceptions += 1
        ledger.peak_tension = max(ledger.peak_tension, ledger.prev_base_tension or 0.0)
        ledger.phrase_cadence[pos.phrase] = "deceptive"  # ration: refuse the tonic
        cap, lock, intensify, rung = self._withholding(ledger)
        extra = (f" [hold {'+'.join(lock)}, melody -{cap}st, push +{round(intensify * 100)}%]"
                 if rung >= 1 else "")
        ledger.last_note = (f"dramaturg: WITHHOLD phrase {pos.phrase} -> deceptive, circle tonic "
                            f"(debt {self._debt(ledger)}, rung {rung}){extra}")
        return Directive(cadence="deceptive", withhold_root_tonic=True, escalation=rung,
                         register_cap=cap, lock_layers=lock, intensify=intensify, note=ledger.last_note)

    def _spend(self, ledger: Ledger, pos: PhrasePos) -> Directive:
        magnitude = spend_magnitude(ledger, self.cfg)
        debt = self._debt(ledger)
        brighten = 2 if magnitude >= self.cfg.big_spend else 1  # a bigger payoff lifts further
        ledger.phrase_cadence[pos.phrase] = "authentic"  # release: the root-position tonic
        ledger.last_spend = magnitude
        ledger.last_note = (f"dramaturg: SPEND phrase {pos.phrase} -> authentic "
                            f"(debt {debt} -> payoff {magnitude:.3f}, mode +{brighten})")
        note = ledger.last_note
        ledger.bars_since_authentic = 0  # cashed — reset the ledger
        ledger.deceptions = 0
        ledger.withholding_phrases = 0
        ledger.peak_tension = 0.0
        return Directive(cadence="authentic", payoff=magnitude, brighten=brighten, note=note)

    def _standing(self, ledger: Ledger) -> Directive:
        """Mid-phrase carry: keep the withholding constraints in force while
        accruing (no ledger change; the phrase-level decision already happened)."""
        if ledger.withholding_phrases <= 0:
            return Directive()
        cap, lock, intensify, rung = self._withholding(ledger)
        return Directive(withhold_root_tonic=True, escalation=rung,
                         register_cap=cap, lock_layers=lock, intensify=intensify)
