import { useEffect, useRef, useState } from "react";
import { useMain } from "../store";
import type { EventDef } from "../protocol";

// A scrolling piano-roll of the last few bars: pitch (y) x time (x), each note a
// bar colored by layer, opacity by velocity. Toggle between the final events
// (post-modifier, what plays) and the raw grid (pre-modifier IR).
const LAYER_COLORS: Record<string, string> = {
  pad: "#4cc2ff",
  bass: "#d2a8ff",
  melody: "#3fb950",
  arp: "#ff9f4c",
  perc: "#8b949e",
};
const PITCH_LO = 28;
const PITCH_HI = 100;
const H = 300;
const PX_PER_BEAT = 42;

export function PianoRoll() {
  const s = useMain();
  const [showRaw, setShowRaw] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [s.roll]);

  if (s.roll.length === 0) {
    return <div className="pgrid-empty">press play to see the roll</div>;
  }

  const evs: EventDef[] = s.roll.flatMap((b) => (showRaw ? b.rawEvents : b.events));
  const t0 = Math.min(...evs.map((e) => e.start));
  const t1 = Math.max(...evs.map((e) => e.start + e.dur));
  const span = Math.max(t1 - t0, 1);
  const width = PX_PER_BEAT * span;
  const x = (t: number) => ((t - t0) / span) * width;
  const y = (p: number) => H - ((clamp(p, PITCH_LO, PITCH_HI) - PITCH_LO) / (PITCH_HI - PITCH_LO)) * H;

  return (
    <div className="roll">
      <div className="roll-bar">
        <span className="meditor-hint">pitch × time · colored by layer · last {s.roll.length} bars</span>
        <div className="roll-legend">
          {Object.entries(LAYER_COLORS).map(([l, c]) => (
            <span className="roll-key" key={l}><i style={{ background: c }} />{l}</span>
          ))}
        </div>
        <button className="btn-sm" onClick={() => setShowRaw((r) => !r)}>
          {showRaw ? "raw grid (pre)" : "final (post)"}
        </button>
      </div>
      <div className="roll-scroll" ref={scrollRef}>
        <svg width={width} height={H} className="roll-svg">
          {barlines(s.roll, x).map((bx, i) => (
            <line key={`bl${i}`} x1={bx} y1={0} x2={bx} y2={H} className="roll-barline" />
          ))}
          {evs.map((e, i) => (
            <rect key={i} x={x(e.start)} y={y(e.pitch) - 3} rx={2}
                  width={Math.max(x(e.start + e.dur) - x(e.start) - 1, 2)} height={6}
                  fill={LAYER_COLORS[e.layer] ?? "#888"} opacity={0.32 + 0.55 * (e.velocity / 127)}>
              <title>{`${e.layer} · ${e.chord || "-"} · ${e.role || "-"} · pitch ${e.pitch} vel ${e.velocity}`}</title>
            </rect>
          ))}
        </svg>
      </div>
    </div>
  );
}

function barlines(roll: { events: EventDef[]; rawEvents: EventDef[] }[], x: (t: number) => number): number[] {
  // a light line at each bar's first event start
  const starts = roll.map((b) => (b.events[0] ?? b.rawEvents[0])?.start).filter((v): v is number => v != null);
  return Array.from(new Set(starts)).map(x);
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}
