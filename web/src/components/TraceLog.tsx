import { useEffect, useRef } from "react";
import { useMain } from "../store";

// The engine's own decision trace, streamed per bar and auto-scrolled — the
// "why did it play that?" inspector.
export function TraceLog() {
  const { trace } = useMain();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [trace]);

  return (
    <div className="trace-log mono" ref={ref}>
      {trace.length === 0 ? (
        <div className="trace-line">no bars yet — press play</div>
      ) : (
        trace.map((line, i) => (
          <div key={i} className={/^bar /.test(line) ? "trace-bar" : "trace-line"}>
            {line}
          </div>
        ))
      )}
    </div>
  );
}
