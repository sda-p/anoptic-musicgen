"""M13 dramaturg / tension-debt ledger (skeleton): the accrue→withhold,
release→spend decision, the monotone payoff, the leniency knob, determinism, and
that a disabled dramaturg is inert. Audio-free — pure generation."""
from __future__ import annotations

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig, Ledger, spend_magnitude

PB = EngineConfig().phrase_bars


def _accrue_release(seed: int, phrases: int, leniency: float = 0.5):
    cfg = EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig(leniency=leniency))
    eng = MusicEngine(seed=seed, config=cfg)
    eng.set_affect(valence=-0.2, energy=0.7, tension=0.85)          # sustained high: accrue
    accrue_cadences = []
    for _ in range(phrases * PB):
        r = eng.advance_bar()
        if r.context.cadence_slot == "cadence":
            accrue_cadences.append(r.context.cadence_policy)
    eng.set_affect(valence=0.5, energy=0.6, tension=0.08)           # drop: release
    release = [eng.advance_bar() for _ in range(PB)]
    rel_cad = next(r.context.cadence_policy for r in release if r.context.cadence_slot == "cadence")
    return accrue_cadences, rel_cad, eng.state.ledger.last_spend


def test_spend_magnitude_strictly_increasing_and_bounded():
    cfg = DramaturgConfig()
    prev = -1.0
    for debt in range(0, 60, 4):
        m = spend_magnitude(Ledger(bars_since_authentic=debt), cfg)
        assert 0.0 <= m < 1.0 and m > prev      # the M13 acceptance property, at the unit level
        prev = m


def test_accrual_withholds_and_release_spends():
    accrue, rel, payoff = _accrue_release(seed=7, phrases=4)
    assert accrue == ["deceptive"] * 4          # every withheld phrase rationed to deceptive
    assert rel == "authentic"                   # the release cashes an authentic cadence
    assert 0.0 < payoff < 1.0


def test_payoff_is_monotone_in_accrual():
    payoffs = [_accrue_release(seed=7, phrases=n)[2] for n in (1, 4, 12)]
    assert payoffs[0] < payoffs[1] < payoffs[2]


def test_leniency_trades_holding_for_release():
    # same buildup, then a *partial* dip (not a full release): a lenient dramaturg
    # spends on the dip; a strict one keeps withholding.
    def dip(leniency: float):
        cfg = EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig(leniency=leniency))
        eng = MusicEngine(seed=3, config=cfg)
        eng.set_affect(tension=0.85)
        for _ in range(4 * PB):
            eng.advance_bar()
        eng.set_affect(tension=0.30)
        for _ in range(PB):
            eng.advance_bar()
        led = eng.state.ledger
        return led.last_spend, led.bars_since_authentic
    lenient_spend, lenient_debt = dip(1.0)
    strict_spend, strict_debt = dip(0.0)
    assert lenient_spend > 0.0 and lenient_debt == 0     # lenient released and reset
    assert strict_spend == 0.0 and strict_debt > 0       # strict kept the debt


def test_withholding_escalates_into_gate_and_register_then_blooms():
    eng = MusicEngine(seed=7, config=EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig()))
    eng.set_affect(valence=-0.2, energy=0.85, tension=0.85)   # energy high enough to gate arp on
    acc = [eng.advance_bar() for _ in range(6 * PB)]

    first = " ".join(acc[0].trace)                            # rung 0: cadence rationed, no suppression yet
    assert "WITHHOLD" in first and "hold" not in first
    deep = acc[5 * PB]                                        # escalated: tier held + melody contracted
    deep_trace = " ".join(deep.trace)
    assert "hold arp" in deep_trace and "melody -" in deep_trace
    assert "arp" not in deep.params.layers                    # the held tier is actually out of the gate set

    eng.set_affect(valence=0.5, energy=0.85, tension=0.05)    # release
    rel = [eng.advance_bar() for _ in range(PB)]
    assert "SPEND" in " ".join(rel[0].trace)
    assert "arp" in rel[1].params.layers                      # the tier snaps back — the bloom


def test_escalation_ladder_builds_then_releases():
    eng = MusicEngine(seed=7, config=EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig()))
    eng.set_affect(valence=-0.2, energy=0.6, tension=0.85)       # sustained: a long withhold
    acc = [eng.advance_bar() for _ in range(10 * PB)]
    vels = [acc[ph * PB].params.velocity_center for ph in range(10)]
    assert vels == sorted(vels) and vels[-1] > vels[0]          # keeps building (non-decreasing, not flat)
    assert vels[-1] == vels[-2]                                 # ...and plateaus at the escalation cap
    eng.set_affect(valence=0.4, energy=0.6, tension=0.05)       # release
    rel = [eng.advance_bar() for _ in range(PB)]
    assert rel[0].params.velocity_center < vels[-1]            # intensity drops back to baseline on the spend


def test_withholding_circles_the_tonic():
    def free_tonics(on: bool):
        cfg = EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig() if on else None)
        eng = MusicEngine(seed=7, config=cfg)
        eng.set_affect(valence=-0.2, energy=0.6, tension=0.85)   # sustained: withhold
        acc = [eng.advance_bar() for _ in range(6 * PB)]
        # non-cadence bars sitting on the tonic (degree 1) = "home" arrivals the walk should avoid
        return sum(1 for r in acc
                   if r.context.cadence_slot != "cadence" and r.context.chord.degree == 1)
    assert free_tonics(True) < free_tonics(False)                # circles the tonic far more while withholding


def test_spend_brightens_the_mode():
    from musicgen.theory.scales import BRIGHTNESS

    def spend(on: bool):
        cfg = EngineConfig(mapper=MappingTable(), dramaturg=DramaturgConfig() if on else None)
        eng = MusicEngine(seed=7, config=cfg)
        eng.set_affect(valence=-0.3, energy=0.6, tension=0.85)   # dark + high: accrue
        for _ in range(4 * PB):
            eng.advance_bar()
        eng.set_affect(valence=-0.1, energy=0.6, tension=0.05)   # release (valence still lowish)
        rel = [eng.advance_bar() for _ in range(PB)]
        return rel[0].context.scale.mode, [t for r in rel for t in r.trace]

    on_mode, on_trace = spend(True)
    off_mode, _ = spend(False)
    assert BRIGHTNESS[on_mode] > BRIGHTNESS[off_mode]           # the spend lifts the mode brighter
    assert any("mode +" in t for t in on_trace)                # ...and the trace records it


def test_deterministic_for_fixed_seed_and_trajectory():
    assert _accrue_release(7, 4) == _accrue_release(7, 4)


def test_disabled_dramaturg_is_inert():
    eng = MusicEngine(seed=7, config=EngineConfig(mapper=MappingTable()))  # dramaturg None (default)
    eng.set_affect(tension=0.85)
    for _ in range(2 * PB):
        eng.advance_bar()
    assert eng.dramaturg is None
    assert eng.state.ledger.phrase_cadence == {} and eng.state.ledger.last_spend == 0.0
