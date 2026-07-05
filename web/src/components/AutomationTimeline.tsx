import { useRef } from "react";
import { useMain } from "../store";
import { api } from "../ws";
import type { AutomationPoint } from "../protocol";

// A drawable affect-automation editor: three stacked lanes (valence / energy /
// tension) of keyframes over bars. This is the demo ARCs (control.automation)
// made interactive — enable it and the engine's affect follows the curve each
// bar instead of the XY-pad. Click a lane to add a keyframe, drag to shape it,
// double-click to remove.

type LaneKey = "valence" | "energy" | "tension";
const LANES: { key: LaneKey; label: string; min: number; max: number; color: string }[] = [
  { key: "valence", label: "valence", min: -1, max: 1, color: "#6ad0ff" },
  { key: "energy", label: "energy", min: 0, max: 1, color: "#ffb454" },
  { key: "tension", label: "tension", min: 0, max: 1, color: "#ff6a8a" },
];

const VBW = 720;
const PAD_L = 40;
const PAD_R = 16;
const PAD_T = 10;
const LANE_H = 54;
const LANE_GAP = 14;
const VBH = PAD_T + LANES.length * LANE_H + (LANES.length - 1) * LANE_GAP + 22;
const PLOT_W = VBW - PAD_L - PAD_R;

const laneTop = (i: number) => PAD_T + i * (LANE_H + LANE_GAP);
const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

function valueAt(points: AutomationPoint[], bar: number, key: LaneKey): number {
  const dflt = key === "valence" ? 0.3 : key === "energy" ? 0.5 : 0.45;
  if (!points.length) return dflt;
  const s = [...points].sort((a, b) => a.bar - b.bar);
  if (bar <= s[0].bar) return s[0][key];
  if (bar >= s[s.length - 1].bar) return s[s.length - 1][key];
  for (let i = 0; i < s.length - 1; i++) {
    const a = s[i], b = s[i + 1];
    if (a.bar <= bar && bar <= b.bar) {
      return b.bar === a.bar ? b[key] : a[key] + (b[key] - a[key]) * ((bar - a.bar) / (b.bar - a.bar));
    }
  }
  return s[s.length - 1][key];
}

export function AutomationTimeline() {
  const { automation, running, bar } = useMain();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const drag = useRef<{ index: number; lane: number } | null>(null);
  const raf = useRef(0);
  const pending = useRef<AutomationPoint[] | null>(null);

  const points = automation.points;
  const loop = automation.loop_bars;
  const maxPtBar = points.reduce((m, p) => Math.max(m, p.bar), 0);
  const span = Math.max(16, loop || 0, maxPtBar + 2);

  const xForBar = (b: number) => PAD_L + (b / span) * PLOT_W;
  const barForX = (x: number) => clamp(Math.round(((x - PAD_L) / PLOT_W) * span), 0, span);
  const yForVal = (lane: number, v: number) => {
    const L = LANES[lane];
    return laneTop(lane) + (1 - (v - L.min) / (L.max - L.min)) * LANE_H;
  };
  const valForY = (lane: number, y: number) => {
    const L = LANES[lane];
    return clamp(L.max - ((y - laneTop(lane)) / LANE_H) * (L.max - L.min), L.min, L.max);
  };

  const toVB = (e: React.PointerEvent | React.MouseEvent) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * VBW, y: ((e.clientY - r.top) / r.height) * VBH };
  };

  // discrete edits (add / remove) send straight to the server. A drag previews
  // to the store at rAF cadence (emit=false → no socket traffic) and sends once
  // on release — the one-send-per-gesture shape Slider / AffectPad use.
  const flush = () => {
    raf.current = 0;
    if (pending.current) api.setAutomation({ points: pending.current }, false);
  };

  const addPoint = (lane: number, e: React.MouseEvent) => {
    const { x, y } = toVB(e);
    const b = barForX(x);
    if (points.some((p) => p.bar === b)) return; // one keyframe per bar
    const np: AutomationPoint = {
      bar: b,
      valence: valueAt(points, b, "valence"),
      energy: valueAt(points, b, "energy"),
      tension: valueAt(points, b, "tension"),
    };
    np[LANES[lane].key] = valForY(lane, y); // the lane you clicked lands under the cursor
    api.setAutomation({ points: [...points, np].sort((a, c) => a.bar - c.bar) });
  };

  const onDotDown = (index: number, lane: number, e: React.PointerEvent) => {
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    drag.current = { index, lane };
  };
  const onMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    const { index, lane } = drag.current;
    const { x, y } = toVB(e);
    pending.current = points.map((p, i) =>
      i === index ? { ...p, bar: barForX(x), [LANES[lane].key]: valForY(lane, y) } : p,
    );
    if (!raf.current) raf.current = requestAnimationFrame(flush);
  };
  const onUp = (e: React.PointerEvent) => {
    if (!drag.current) return;
    (e.target as Element).releasePointerCapture?.(e.pointerId);
    drag.current = null;
    if (raf.current) { cancelAnimationFrame(raf.current); raf.current = 0; }
    const final = pending.current ?? points;
    pending.current = null;
    api.setAutomation({ points: [...final].sort((a, c) => a.bar - c.bar) }); // commit once
  };
  const removePoint = (index: number) => {
    if (points.length <= 1) return; // keep at least one keyframe
    api.setAutomation({ points: points.filter((_, i) => i !== index) });
  };

  const sorted = [...points].sort((a, b) => a.bar - b.bar);
  const nowBar = running && bar != null ? (loop > 0 ? bar % loop : bar) : null;

  return (
    <div className="automation">
      <div className="automation-controls">
        <label className={`toggle ${automation.enabled ? "on" : ""}`}>
          <input
            type="checkbox"
            checked={automation.enabled}
            onChange={(e) => api.setAutomation({ enabled: e.target.checked })}
          />
          {automation.enabled ? "automation drives affect" : "automation off (XY-pad drives)"}
        </label>
        <label className="loop">
          loop&nbsp;bars
          <input
            className="mono"
            type="number"
            min={0}
            value={loop}
            onChange={(e) => api.setAutomation({ loop_bars: Math.max(0, Number(e.target.value) || 0) })}
          />
          <span className="hint">{loop > 0 ? `repeats every ${loop}` : "one-shot, then holds"}</span>
        </label>
      </div>

      <svg
        ref={svgRef}
        className="automation-svg"
        viewBox={`0 0 ${VBW} ${VBH}`}
        onPointerMove={onMove}
        onPointerUp={onUp}
      >
        {LANES.map((L, li) => {
          const top = laneTop(li);
          const zeroY = L.min < 0 ? yForVal(li, 0) : null;
          const path = sorted.length
            ? [
                `M ${xForBar(0)} ${yForVal(li, sorted[0][L.key])}`,
                ...sorted.map((p) => `L ${xForBar(p.bar)} ${yForVal(li, p[L.key])}`),
                `L ${xForBar(span)} ${yForVal(li, sorted[sorted.length - 1][L.key])}`,
              ].join(" ")
            : "";
          return (
            <g key={L.key}>
              <rect
                className="lane-bg"
                x={PAD_L}
                y={top}
                width={PLOT_W}
                height={LANE_H}
                onClick={(e) => addPoint(li, e)}
              />
              {zeroY != null && (
                <line className="lane-zero" x1={PAD_L} y1={zeroY} x2={PAD_L + PLOT_W} y2={zeroY} />
              )}
              <text className="lane-label" x={4} y={top + 12}>{L.label}</text>
              {loop > 0 && (
                <line className="loop-mark" x1={xForBar(loop)} y1={top} x2={xForBar(loop)} y2={top + LANE_H} />
              )}
              {path && <path className="lane-curve" style={{ stroke: L.color }} d={path} />}
              {points.map((p, pi) => (
                <circle
                  key={pi}
                  className="lane-dot"
                  style={{ fill: L.color }}
                  cx={xForBar(p.bar)}
                  cy={yForVal(li, p[L.key])}
                  r={5}
                  onPointerDown={(e) => onDotDown(pi, li, e)}
                  onDoubleClick={() => removePoint(pi)}
                />
              ))}
            </g>
          );
        })}
        {nowBar != null && (
          <line className="playhead" x1={xForBar(nowBar)} y1={PAD_T} x2={xForBar(nowBar)} y2={VBH - 20} />
        )}
        <text className="axis-tick" x={PAD_L} y={VBH - 6}>bar 0</text>
        <text className="axis-tick" x={VBW - PAD_R} y={VBH - 6} textAnchor="end">bar {span}</text>
      </svg>
      <div className="hint automation-hint">
        click a lane to add a keyframe · drag to shape · double-click to remove
      </div>
    </div>
  );
}
