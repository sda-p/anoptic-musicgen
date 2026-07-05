import { useMain } from "../store";

// The "what is it doing right now" panel: key/mode, current -> next chord,
// tempo, cadence, and the derived params the engine actually used this bar.
export function TelemetryHeader() {
  const { context: c, params: p, bar } = useMain();
  if (!c || !p) {
    return <div className="now-empty">press ▶ play to start the engine</div>;
  }
  return (
    <div className="now-grid">
      <Field label="bar" value={String((bar ?? 0) + 1)} />
      <Field label="key / mode" value={c.scale} />
      <Field label="chord" value={c.chord_sym || "—"} sub={`→ ${c.next_chord_sym}`} />
      <Field label="tempo" value={`${p.tempo_bpm.toFixed(1)}`} sub="bpm" />
      <Field label="cadence" value={c.cadence_slot ? c.cadence_slot : "—"} sub={c.cadence_policy} />
      <Field label="tension" value={c.tension.toFixed(2)} />
      <Field label="density" value={p.note_density.toFixed(2)} />
      <Field label="register" value={String(p.register_center)} />
      <Field label="layers" value={p.layers.join(" ")} />
      {c.modulation && <Field label="modulation" value={c.modulation} wide />}
    </div>
  );
}

function Field(props: { label: string; value: string; sub?: string; wide?: boolean }) {
  return (
    <div className={`field${props.wide ? " field-wide" : ""}`}>
      <div className="field-label">{props.label}</div>
      <div className="field-value">
        {props.value}
        {props.sub ? <span className="field-sub">{props.sub}</span> : null}
      </div>
    </div>
  );
}
