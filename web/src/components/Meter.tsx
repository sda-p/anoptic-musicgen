import { useMeter } from "../store";

// Master output level + CPU + bars-played, fed by the 30 fps meter store (kept
// separate so these updates never re-render the telemetry panels).
export function Meter() {
  const m = useMeter();
  const pct = Math.min(100, m.level * 100);
  return (
    <div className="meter">
      <div className="meter-row">
        <span className="control-label-inline">level</span>
        <div className="meter-track">
          <div className="meter-fill" style={{ width: `${pct}%` }} />
        </div>
      </div>
      <div className="meter-stats mono">
        <span>cpu {(m.cpu * 100).toFixed(0)}%</span>
        <span>bars {m.bars}</span>
      </div>
    </div>
  );
}
