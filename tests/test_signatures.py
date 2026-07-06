"""M17 authored signature selection (§5.5): the MotifDirector weighs a ticking
overdue×importance pressure against theory-appropriateness (best-fitting transform),
with leniency trading recurrence frequency for fit; request_motif forces a tag; an
empty library selects nothing. Pure selection logic — no engine wiring yet."""

from collections import Counter

from musicgen.gen.signatures import EXAMPLE_LIBRARY, MotifDirector, SignatureMotif
from musicgen.theory.chords import Chord
from musicgen.theory.scales import Scale

SCALE = Scale(0, "ionian")
STRONG, LO, HI = {0, 4, 8, 12}, 60, 84
PROG = [1, 4, 5, 6, 2, 5, 1, 4, 6, 5, 1, 4, 5, 6, 2, 5]


def _run(leniency, library=EXAMPLE_LIBRARY, requests=None):
    d = MotifDirector(library=library)
    launches = []
    for i, deg in enumerate(PROG):
        pcs = Chord(deg).pitch_classes(SCALE)
        sel = d.select(SCALE, pcs, LO, HI, STRONG, leniency, near=72,
                       requested=(requests or {}).get(i, ""))
        if sel:
            launches.append((i, sel[0].tag))
            d.observe(sel[0].tag, 8)
        else:
            d.age(8)
    return launches


def test_leniency_trades_recurrence_for_fit():
    assert len(_run(0.1)) < len(_run(0.9))          # lenient states signatures more often


def test_importance_drives_frequency():
    counts = Counter(tag for _, tag in _run(0.3))
    assert counts["hero"] > counts["threat"]        # the landmark recurs more than the colour


def test_request_forces_a_tag():
    launches = _run(0.3, requests={0: "threat"})     # threat, though hero is more important
    assert launches and launches[0] == (0, "threat")


def test_empty_library_selects_none():
    d = MotifDirector()
    assert d.select(SCALE, Chord(1).pitch_classes(SCALE), LO, HI, STRONG, 0.9, near=72) is None


def test_recently_stated_motif_yields_to_the_overdue_one():
    d = MotifDirector(library=EXAMPLE_LIBRARY)
    d.observe("hero", 8)                             # hero just heard; threat never
    sel = d.select(SCALE, Chord(4).pitch_classes(SCALE), LO, HI, STRONG, 0.5, near=72)
    assert sel and sel[0].tag == "threat"


def test_selection_is_deterministic():
    assert _run(0.5) == _run(0.5)


def test_transform_widens_placement():
    # a motif whose identity fits nowhere well can still land via a transform: the
    # director returns a (possibly transformed) cell it deems appropriate.
    d = MotifDirector(library=EXAMPLE_LIBRARY)
    sel = d.select(SCALE, Chord(6).pitch_classes(SCALE), LO, HI, STRONG, 0.9, near=72)
    assert sel is not None
    _, transform, motif_t = sel
    assert transform in ("identity", "inversion", "displacement", "truncation")


# --- engine integration (M17.2): the director states signatures in the melody ---

from musicgen.control.mapping import MappingTable          # noqa: E402
from musicgen.gen.conductor import EngineConfig, MusicEngine  # noqa: E402
from musicgen.gen.dramaturg import DramaturgConfig         # noqa: E402
from musicgen.ir import Meter                              # noqa: E402
from musicgen.verify import lint                           # noqa: E402


def _render(library, seed=42, phrases=10, dramaturg=True):
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(), motif_library=library,
                       dramaturg=DramaturgConfig(leniency=0.5) if dramaturg else None)
    eng = MusicEngine(seed=seed, config=cfg)
    pb = cfg.phrase_bars
    results = []
    eng.set_affect(valence=0.2, energy=0.6, tension=0.4)   # steady: no dramaturg spend
    for _ in range(phrases * pb):
        results.append(eng.advance_bar())
    return results


def test_engine_states_and_lints_signatures():
    results = _render(EXAMPLE_LIBRARY)
    raw = [e for r in results for e in r.raw_events]
    ctxs = [r.context for r in results]
    assert [e for e in raw if e.role == "motif"], "authored signatures are stated faithfully"
    assert lint(raw, ctxs, Meter(), stage="pre") == []


def test_empty_library_plants_no_signatures():
    raw = [e for r in _render((), dramaturg=False) for e in r.raw_events]
    assert not [e for e in raw if e.role == "motif"]       # nothing to state → byte-identical


def test_signature_render_is_deterministic():
    key = lambda e: (e.start, e.layer, e.pitch, e.role)  # noqa: E731
    a = [key(e) for r in _render(EXAMPLE_LIBRARY) for e in r.raw_events]
    b = [key(e) for r in _render(EXAMPLE_LIBRARY) for e in r.raw_events]
    assert a == b


def test_request_motif_states_the_tag_next_phrase():
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(), motif_library=EXAMPLE_LIBRARY,
                       dramaturg=DramaturgConfig(leniency=0.3))
    eng = MusicEngine(seed=3, config=cfg)
    pb = cfg.phrase_bars
    eng.set_affect(valence=0.2, energy=0.6, tension=0.4)
    for _ in range(pb):
        eng.advance_bar()                       # phrase 0
    eng.request_motif("threat")                 # the game binds meaning
    results = [eng.advance_bar() for _ in range(pb)]   # phrase 1
    assert [t for r in results for t in r.trace if "signature 'threat'" in t]
    assert eng.state.requested_motif == ""      # honoured and consumed


def test_landmark_lands_as_an_arrival():
    # under sustained tension the dramaturg withholds (deceptive cadences); a landmark
    # hero statement forces its phrase to an authentic cadence, cashing the debt, with
    # the M14 cadential dissonance following — all lint clean.
    cfg = EngineConfig(meter=Meter(), mapper=MappingTable(), motif_library=EXAMPLE_LIBRARY,
                       dramaturg=DramaturgConfig(leniency=0.4))
    eng = MusicEngine(seed=7, config=cfg)
    pb = cfg.phrase_bars
    results = []
    eng.set_affect(valence=-0.3, energy=0.7, tension=0.85)
    for _ in range(8 * pb):
        results.append(eng.advance_bar())
    landmark_phrases = {r.bar // pb for r in results
                        if any("spends the ledger" in t for t in r.trace)}
    assert landmark_phrases, "a landmark should spend the ledger under sustained tension"
    for ph in landmark_phrases:
        cadence = next(r for r in results if r.bar // pb == ph and r.context.cadence_slot == "cadence")
        assert cadence.context.cadence_policy == "authentic"          # landed as an arrival
        assert any(e.role in ("suspension", "appoggiatura")           # with M14 cadential dissonance
                   for r in results if r.bar // pb == ph for e in r.raw_events)
    raw = [e for r in results for e in r.raw_events]
    ctxs = [r.context for r in results]
    assert lint(raw, ctxs, Meter(), stage="pre") == []
