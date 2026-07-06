"""M14 earned dissonance (§5.8): a planted structural dissonance must discharge.

The linter (obligation-checking) is exercised directly on hand-built IR — the
clean cases pass, and every *deliberately unresolved plant* is caught (the M14
acceptance property). The realization side (M14.2) is exercised too: the pad
turns a prepared voice into a resolving suspension, and the dramaturg deploys them
over the cadences it controls — planting only where a prepared voice exists, so
they always discharge."""

from musicgen.control.mapping import MappingTable
from musicgen.gen.conductor import EngineConfig, MusicEngine
from musicgen.gen.dramaturg import DramaturgConfig
from musicgen.gen.pad import _suspension_pair
from musicgen.ir import HarmonicContext, Meter, NoteEvent
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale
from musicgen.verify import lint

METER = Meter(4, 4)
SCALE = Scale(0, "ionian")


def _rules(events, contexts):
    return [v.rule for v in lint(events, contexts, METER, stage="pre")]


def _ctx(bar, sym, pcs, **kw):
    return HarmonicContext(bar=bar, scale=SCALE, chord_sym=sym, chord_pcs=pcs, **kw)


# --- suspensions: prepared, then resolve down by step to a chord tone ---------

def _suspension(resolve_to=64, prepare=True):
    """Bar 0 = ii (Dm), F is a chord tone (the preparation); bar 1 = I (C), the
    held F is a 4–3 suspension resolving (or not) at beat 3."""
    contexts = [_ctx(0, "ii", (2, 5, 9)), _ctx(1, "I", (0, 4, 7))]
    events = [
        NoteEvent(4.0, 4.0, 60, 74, "pad", role="chord-tone"),   # C sustained under
        NoteEvent(4.0, 2.0, 65, 74, "pad", role="suspension"),   # F suspended over C
    ]
    if prepare:
        events.append(NoteEvent(0.0, 4.0, 65, 74, "pad", role="chord-tone"))  # F prepared over Dm
    if resolve_to is not None:
        events.append(NoteEvent(6.0, 2.0, resolve_to, 74, "pad", role="resolution"))
    return events, contexts


def test_resolved_suspension_clean():
    assert lint(*_suspension(), METER, stage="pre") == []


def test_unresolved_suspension_flagged():
    events, contexts = _suspension(resolve_to=None)  # F just stops, never resolves
    assert "suspension" in _rules(events, contexts)


def test_suspension_resolving_up_flagged():
    events, contexts = _suspension(resolve_to=67)  # F -> G, up a step, not a resolution
    assert "suspension" in _rules(events, contexts)


def test_suspension_resolving_by_leap_flagged():
    events, contexts = _suspension(resolve_to=60)  # F -> C, a chord tone but a leap, not a step
    assert "suspension" in _rules(events, contexts)


def test_unprepared_suspension_flagged():
    events, contexts = _suspension(prepare=False)  # F appears from nowhere
    assert "suspension-prep" in _rules(events, contexts)
    assert "suspension" not in _rules(events, contexts)  # it does still resolve


# --- pedal points: a contiguous same-pitch bass run terminates at a cadence ---

def _pedal(cadence_at_bar2=True):
    """G held in the bass under IV then V (bars 0–1), resolving as the I cadence
    arrives at bar 2."""
    contexts = [
        _ctx(0, "IV", (5, 9, 0)),
        _ctx(1, "V", (7, 11, 2)),
        _ctx(2, "I", (0, 4, 7), cadence_slot="cadence" if cadence_at_bar2 else "",
             cadence_policy="authentic" if cadence_at_bar2 else ""),
    ]
    events = [
        NoteEvent(0.0, 4.0, 43, 82, "bass", role="pedal"),   # G under IV (not the root)
        NoteEvent(4.0, 4.0, 43, 82, "bass", role="pedal"),   # G under V (is the root)
        NoteEvent(8.0, 4.0, 36, 82, "bass", role="root"),    # C, resolution at the cadence
    ]
    return events, contexts


def test_pedal_terminating_at_cadence_clean():
    assert lint(*_pedal(), METER, stage="pre") == []


def test_pedal_without_cadence_flagged():
    events, contexts = _pedal(cadence_at_bar2=False)
    assert "pedal" in _rules(events, contexts)


# --- context obligations: borrowing returns; a secondary dominant resolves ----

def test_borrowed_returns_to_diatonic_clean():
    contexts = [
        HarmonicContext(bar=0, scale=SCALE, chord=Chord(6, source_mode="aeolian"),
                        chord_sym="bVI", chord_pcs=(8, 0, 3), obligation="borrowed"),
        HarmonicContext(bar=1, scale=SCALE, chord=Chord(4), chord_sym="IV", chord_pcs=(5, 9, 0)),
    ]
    assert lint([], contexts, METER, stage="pre") == []


def test_borrowed_stuck_flagged():
    contexts = [
        HarmonicContext(bar=0, scale=SCALE, chord=Chord(6, source_mode="aeolian"),
                        chord_sym="bVI", chord_pcs=(8, 0, 3), obligation="borrowed"),
        HarmonicContext(bar=1, scale=SCALE, chord=Chord(4, source_mode="aeolian"),
                        chord_sym="iv", chord_pcs=(5, 8, 0)),
        HarmonicContext(bar=2, scale=SCALE, chord=Chord(7, source_mode="aeolian"),
                        chord_sym="bVII", chord_pcs=(10, 2, 5)),
    ]
    assert "borrowed" in [v.rule for v in lint([], contexts, METER, stage="pre")]


def test_secondary_dominant_resolves_clean():
    contexts = [
        HarmonicContext(bar=0, scale=SCALE, chord=Chord(2), chord_sym="V/V",
                        chord_pcs=(2, 6, 9), obligation="tonicize:5"),
        HarmonicContext(bar=1, scale=SCALE, chord=Chord(5), chord_sym="V", chord_pcs=(7, 11, 2)),
    ]
    assert lint([], contexts, METER, stage="pre") == []


def test_secondary_dominant_unresolved_flagged():
    contexts = [
        HarmonicContext(bar=0, scale=SCALE, chord=Chord(2), chord_sym="V/V",
                        chord_pcs=(2, 6, 9), obligation="tonicize:5"),
        HarmonicContext(bar=1, scale=SCALE, chord=Chord(1), chord_sym="I", chord_pcs=(0, 4, 7)),
    ]
    assert "tonicize" in [v.rule for v in lint([], contexts, METER, stage="pre")]


# --- dormant on output that plants nothing (byte-identical lint on pre-M14) ---

def test_no_obligations_is_silent():
    """Ordinary events with no obligation roles/fields must not trip any of the
    new rules — pre-M14 renders lint exactly as before."""
    events = [
        NoteEvent(0.0, 4.0, 60, 74, "pad", role="chord-tone"),
        NoteEvent(0.0, 4.0, 64, 74, "pad", role="chord-tone"),
        NoteEvent(0.0, 4.0, 36, 82, "bass", role="root"),
        NoteEvent(0.0, 1.0, 72, 80, "melody", degree=1, role="chord-tone"),
    ]
    contexts = [_ctx(0, "I", (0, 4, 7))]
    rules = _rules(events, contexts)
    assert not ({"suspension", "suspension-prep", "pedal", "borrowed", "tonicize"} & set(rules))


# --- pad realization: a prepared voice becomes a resolving suspension (M14.2) --

def _I():
    return HarmonicContext(bar=1, scale=SCALE, chord=Chord(1), chord_sym="I", chord_pcs=(0, 4, 7))


def test_suspension_pair_finds_highest_prepared_step():
    # over I(C E G): D(62) still sounding is a 9–8 suspension resolving to C(60);
    # A(57) is a prepared 6–5 over G — the higher dissonance (D) wins.
    assert _suspension_pair((55, 60, 64, 67), (57, 62, 64, 67), _I()) == (60, 62)


def test_suspension_pair_requires_preparation():
    assert _suspension_pair((55, 60, 64, 67), (55, 60, 64, 67), _I()) is None  # nothing held over


def test_suspension_pair_rejects_chromatic():
    # C#(61) is a step above C(60) but not diatonic — a suspension must be clean.
    assert _suspension_pair((55, 60, 64, 67), (55, 61, 64, 67), _I()) is None


# --- the dramaturg deploys suspensions over the cadences it controls ----------

def _dramaturg_render(earned, phrases=4, seed=42):
    cfg = EngineConfig(meter=METER, mapper=MappingTable(),
                       dramaturg=DramaturgConfig(leniency=0.5, earned_dissonance=earned))
    eng = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    eng.set_affect(valence=-0.2, energy=0.7, tension=0.85)   # sustained high: accrue
    for _ in range(phrases * pb):
        results.append(eng.advance_bar())
    eng.set_affect(valence=0.5, energy=0.6, tension=0.08)    # drop: release
    for _ in range(2 * pb):
        results.append(eng.advance_bar())
    return results


def test_dramaturg_deploys_resolving_suspensions():
    results = _dramaturg_render(earned=True)
    raw = [ev for r in results for ev in r.raw_events]
    contexts = [r.context for r in results]
    assert [ev for ev in raw if ev.role == "suspension"], "cadences should be ornamented"
    assert lint(raw, contexts, METER, stage="pre") == []      # and every one discharges


def test_dramaturg_deploys_terminating_pedal():
    results = _dramaturg_render(earned=True)      # 4 withholding phrases: the pedal engages
    raw = [ev for r in results for ev in r.raw_events]
    contexts = [r.context for r in results]
    pedals = [ev for ev in raw if ev.role == "pedal"]
    assert pedals, "sustained withholding should engage a dominant pedal"
    assert len({ev.pitch for ev in pedals}) == 1, "a pedal point holds one fixed pitch"
    assert lint(raw, contexts, METER, stage="pre") == []      # and it terminates at a cadence


# --- appoggiaturas: the unprepared payoff lean, scoped to the pad (M14.4) ------

def test_pad_appoggiatura_resolves_clean():
    # over I(C E G): an unprepared D leans in and resolves down to C — no
    # preparation required (unlike a suspension).
    events = [
        NoteEvent(0.0, 4.0, 64, 74, "pad", role="chord-tone"),   # E sustained
        NoteEvent(0.0, 4.0, 67, 74, "pad", role="chord-tone"),   # G sustained
        NoteEvent(0.0, 2.0, 62, 74, "pad", role="appoggiatura"), # D leaning in, unprepared
        NoteEvent(2.0, 2.0, 60, 74, "pad", role="resolution"),   # -> C
    ]
    assert lint(events, [_ctx(0, "I", (0, 4, 7))], METER, stage="pre") == []


def test_pad_appoggiatura_unresolved_flagged():
    events = [
        NoteEvent(0.0, 4.0, 64, 74, "pad", role="chord-tone"),
        NoteEvent(0.0, 4.0, 67, 74, "pad", role="chord-tone"),
        NoteEvent(0.0, 2.0, 62, 74, "pad", role="appoggiatura"),  # D just stops, never resolves
    ]
    assert "appoggiatura" in _rules(events, [_ctx(0, "I", (0, 4, 7))])


def test_melodic_appoggiatura_is_exempt():
    # the melody's appoggiaturas pass through non-chord tones mid-run; the pad-only
    # obligation must not touch them (an unresolved melodic one is not flagged).
    events = [NoteEvent(0.25, 0.75, 62, 80, "melody", role="appoggiatura")]  # offbeat D, unresolved
    assert "appoggiatura" not in _rules(events, [_ctx(0, "I", (0, 4, 7))])


def test_dramaturg_leans_appoggiatura_when_no_suspension():
    # seed 1's payoff cadence has no preparable suspension, so the pad leans in
    # with an unprepared appoggiatura — which still resolves.
    results = _dramaturg_render(earned=True, seed=1)
    raw = [ev for r in results for ev in r.raw_events]
    contexts = [r.context for r in results]
    assert [ev for ev in raw if ev.role == "appoggiatura" and ev.layer == "pad"]
    assert lint(raw, contexts, METER, stage="pre") == []


def test_earned_dissonance_off_is_inert():
    on = [ev for r in _dramaturg_render(earned=True) for ev in r.raw_events]
    off = [ev for r in _dramaturg_render(earned=False) for ev in r.raw_events]
    assert not any(ev.role in ("suspension", "resolution", "pedal") for ev in off)
    # surgical: earned dissonance touches only the pad (suspensions) and the bass
    # (pedals); every layer on an independent RNG stream is byte-identical, since
    # per-bar streams mean a changed bar can't perturb any other.
    key = lambda e: (e.start, e.layer, e.pitch, e.dur, e.velocity, e.role)  # noqa: E731
    for layer in ("melody", "arp", "perc"):
        assert (sorted(key(e) for e in on if e.layer == layer)
                == sorted(key(e) for e in off if e.layer == layer)), layer
