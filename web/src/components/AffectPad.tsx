import { useEffect, useRef, useState } from "react";
import { useMain } from "../store";
import { api } from "../ws";

// XY pad: valence on x (-1 dark .. +1 bright), energy on y (0 bottom .. 1 top).
// The handle is the user's target (local, so dragging never thrashes the
// store); the dashed ghost is the engine's actually-sounding affect, which
// lags by the look-ahead — making the control latency visible.
export function AffectPad() {
  const s = useMain();
  const [target, setTarget] = useState({ v: s.snapshotAffect.valence, e: s.snapshotAffect.energy });
  const touched = useRef(false);
  const dragging = useRef(false);
  const raf = useRef(0);
  const pending = useRef<{ valence: number; energy: number }>({ valence: 0, energy: 0 });

  useEffect(() => {
    if (!touched.current) setTarget({ v: s.snapshotAffect.valence, e: s.snapshotAffect.energy });
  }, [s.snapshotAffect]);

  const flush = () => {
    raf.current = 0;
    api.setAffect(pending.current);
  };
  const push = (valence: number, energy: number) => {
    pending.current = { valence, energy };
    if (!raf.current) raf.current = requestAnimationFrame(flush);
  };
  const read = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const v = clamp(((e.clientX - r.left) / r.width) * 2 - 1, -1, 1);
    const en = clamp(1 - (e.clientY - r.top) / r.height, 0, 1);
    return { v, en };
  };
  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    touched.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    const { v, en } = read(e);
    setTarget({ v, e: en });
    push(v, en);
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const { v, en } = read(e);
    setTarget({ v, e: en });
    push(v, en);
  };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const hx = ((target.v + 1) / 2) * 100;
  const hy = (1 - target.e) * 100;
  const gx = ((s.engineAffect.valence + 1) / 2) * 100;
  const gy = (1 - s.engineAffect.energy) * 100;

  return (
    <div className="control">
      <div className="control-label">
        <span>valence · energy</span>
        <span className="mono">
          {target.v.toFixed(2)} · {target.e.toFixed(2)}
        </span>
      </div>
      <div className="pad" onPointerDown={down} onPointerMove={move} onPointerUp={up}>
        <div className="pad-axis pad-axis-x" />
        <div className="pad-axis pad-axis-y" />
        <div className="pad-ghost" style={{ left: `${gx}%`, top: `${gy}%` }} title="engine (actual)" />
        <div className="pad-handle" style={{ left: `${hx}%`, top: `${hy}%` }} />
      </div>
      <div className="pad-legend">
        <span>◀ dark</span>
        <span>bright ▶</span>
      </div>
    </div>
  );
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}
