"""Human-readable renderings of the IR (PLANS.md §8.2).

dump_bars: annotated per-bar view, readable against a theory textbook.
dump_events: one line per event, grep-able.
"""

from __future__ import annotations

from typing import Sequence

from musicgen.ir import LAYER_NAMES, HarmonicContext, Meter, MusicalParams, NoteEvent
from musicgen.theory.pitch import pitch_name

_DUR_SYMBOLS = (
    (4.0, "w"), (3.0, "h."), (2.0, "h"), (1.5, "q."),
    (1.0, "q"), (0.75, "e."), (0.5, "e"), (0.375, "s."), (0.25, "s"),
)


def dur_symbol(dur: float) -> str:
    for value, symbol in _DUR_SYMBOLS:
        if abs(dur - value) < 1e-9:
            return symbol
    return f"{dur:g}b"


def _event_line(ev: NoteEvent, meter: Meter) -> str:
    degree = f"^{ev.degree}" if ev.degree else "-"
    name = "-" if ev.layer == "perc" else pitch_name(ev.pitch)
    return (
        f"{meter.beat_in_bar(ev.start):>5.2f} {dur_symbol(ev.dur):<3} "
        f"{name:<4} {degree:<3} {ev.role or '-':<10} v{ev.velocity}"
    )


def dump_bars(
    events: Sequence[NoteEvent],
    contexts: Sequence[HarmonicContext],
    meter: Meter = Meter(),
    params: MusicalParams | None = None,
    *,
    params_by_bar: dict[int, MusicalParams] | None = None,
    affect_by_bar: dict[int, tuple[float, float, float]] | None = None,
) -> str:
    ctx_by_bar = {c.bar: c for c in contexts}
    by_bar: dict[int, list[NoteEvent]] = {}
    for ev in sorted(events, key=lambda e: (e.start, e.pitch)):
        by_bar.setdefault(meter.bar_of(ev.start), []).append(ev)

    lines: list[str] = []
    for bar in sorted(set(by_bar) | set(ctx_by_bar)):
        ctx = ctx_by_bar.get(bar)
        head = [f"── bar {bar + 1:>3}"]
        if ctx is not None:
            head.append(ctx.scale.name)
            if ctx.chord_sym:
                arrow = f" → {ctx.next_chord_sym}" if ctx.next_chord_sym else ""
                head.append(f"{ctx.chord_sym}{arrow}")
            head.append(f"tension {ctx.tension:.2f}")
            if ctx.cadence_slot:
                policy = f" ({ctx.cadence_policy})" if ctx.cadence_policy else ""
                head.append(f"{ctx.cadence_slot}{policy}")
            if ctx.modulation:
                head.append(f"◆ {ctx.modulation}")
        if params is not None:
            head.append(f"{params.tempo_bpm:g} BPM")
        lines.append(" │ ".join(head))
        bar_params = params_by_bar.get(bar) if params_by_bar else None
        if bar_params is not None:
            bits = []
            if affect_by_bar and bar in affect_by_bar:
                v, e, t = affect_by_bar[bar]
                bits.append(f"val {v:+.2f} en {e:.2f} ten {t:.2f}")
            bits.append(f"{bar_params.tempo_bpm:.1f} BPM")
            bits.append(
                f"dens {bar_params.note_density:.2f} rough {bar_params.roughness:.2f} "
                f"art {bar_params.articulation:.2f} vel {bar_params.velocity_center} "
                f"reg {bar_params.register_center}"
            )
            bits.append(
                f"dsp cut {bar_params.filter_cutoff / 1000:.1f}k rev {bar_params.reverb_send:.2f} "
                f"dly {bar_params.delay_send:.2f} drv {bar_params.drive:.2f}"
            )
            bits.append("layers " + ("+".join(bar_params.layers) or "-"))
            lines.append("   levers │ " + " │ ".join(bits))
        for layer in LAYER_NAMES:
            layer_events = [e for e in by_bar.get(bar, []) if e.layer == layer]
            for i, ev in enumerate(layer_events):
                tag = layer if i == 0 else ""
                lines.append(f"   {tag:<7}│ {_event_line(ev, meter)}")
        lines.append("")
    return "\n".join(lines)


def dump_events(events: Sequence[NoteEvent], meter: Meter = Meter()) -> str:
    lines = ["bar  beat   dur    layer   pitch name  vel  deg  role       chord"]
    for ev in sorted(events, key=lambda e: (e.start, e.pitch)):
        degree = f"^{ev.degree}" if ev.degree else "-"
        lines.append(
            f"{meter.bar_of(ev.start) + 1:<4} {meter.beat_in_bar(ev.start):<6.2f} {ev.dur:<6g} {ev.layer:<7} "
            f"{ev.pitch:<5} {pitch_name(ev.pitch):<5} {ev.velocity:<4} {degree:<4} "
            f"{ev.role or '-':<10} {ev.chord or '-'}"
        )
    return "\n".join(lines)
