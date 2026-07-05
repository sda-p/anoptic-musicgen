import { useEffect, useRef, useState } from "react";
import { useMain } from "../store";
import { api } from "../ws";

// Vertical fader for tension (0 bottom .. 1 top). Same local-target-plus-ghost
// pattern as the pad.
export function TensionFader() {
  const s = useMain();
  const [t, setT] = useState(s.snapshotAffect.tension);
  const touched = useRef(false);
  const dragging = useRef(false);
  const raf = useRef(0);
  const pending = useRef(0);

  useEffect(() => {
    if (!touched.current) setT(s.snapshotAffect.tension);
  }, [s.snapshotAffect]);

  const flush = () => {
    raf.current = 0;
    api.setAffect({ tension: pending.current });
  };
  const push = (v: number) => {
    pending.current = v;
    if (!raf.current) raf.current = requestAnimationFrame(flush);
  };
  const read = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return clamp(1 - (e.clientY - r.top) / r.height, 0, 1);
  };
  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    touched.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    const v = read(e);
    setT(v);
    push(v);
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    const v = read(e);
    setT(v);
    push(v);
  };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return (
    <div className="control">
      <div className="control-label">
        <span>tension</span>
        <span className="mono">{t.toFixed(2)}</span>
      </div>
      <div className="fader" onPointerDown={down} onPointerMove={move} onPointerUp={up}>
        <div className="fader-fill" style={{ height: `${t * 100}%` }} />
        <div className="fader-ghost" style={{ top: `${(1 - s.engineAffect.tension) * 100}%` }} title="engine (actual)" />
        <div className="fader-handle" style={{ top: `${(1 - t) * 100}%` }} />
      </div>
    </div>
  );
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}
