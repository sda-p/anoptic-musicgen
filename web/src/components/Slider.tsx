import { useRef } from "react";

// 1D slider with an optional "ghost" tick (the mapper's would-be value). Drag
// is throttled to one send per frame. Disabled sliders still track their value
// (a following param whose value the mapper is moving), just not draggable.
export function Slider(props: {
  min: number;
  max: number;
  step: number;
  value: number;
  ghost?: number | null;
  disabled?: boolean;
  onChange: (v: number) => void;
}) {
  const { min, max, step, value, ghost, disabled } = props;
  const raf = useRef(0);
  const pending = useRef(value);
  const dragging = useRef(false);

  const to01 = (v: number) => clamp((v - min) / (max - min || 1), 0, 1);
  const flush = () => {
    raf.current = 0;
    props.onChange(pending.current);
  };
  const push = (v: number) => {
    pending.current = v;
    if (!raf.current) raf.current = requestAnimationFrame(flush);
  };
  const read = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const t = clamp((e.clientX - r.left) / r.width, 0, 1);
    return clamp(Math.round((min + t * (max - min)) / step) * step, min, max);
  };
  const down = (e: React.PointerEvent<HTMLDivElement>) => {
    if (disabled) return;
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    push(read(e));
  };
  const move = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragging.current) push(read(e));
  };
  const up = (e: React.PointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  const pct = to01(value) * 100;
  const gpct = ghost != null && Number.isFinite(ghost) ? to01(ghost) * 100 : null;
  return (
    <div className={`slider${disabled ? " disabled" : ""}`}
         onPointerDown={down} onPointerMove={move} onPointerUp={up}>
      <div className="slider-fill" style={{ width: `${pct}%` }} />
      {gpct != null && <div className="slider-ghost" style={{ left: `${gpct}%` }} title="mapper target" />}
      <div className="slider-handle" style={{ left: `${pct}%` }} />
    </div>
  );
}

function clamp(x: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, x));
}
