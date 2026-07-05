import { useEffect, useRef, useState } from "react";
import type { MappingFieldSpec, MappingGroup } from "../protocol";

// Reusable grouped number-field grid with diff-from-default highlight and a
// per-field revert. Used by both the heuristics editor (immediate hot-swap) and
// the console tuner (staged, applied on rebuild); the parent decides what
// onEdit does.
export function ConstantsGrid(props: {
  ui: MappingGroup[];
  values: Record<string, unknown>;
  defaults: Record<string, unknown>;
  onEdit: (field: string, value: unknown) => void;
}) {
  return (
    <div className="cgrid-cols">
      {props.ui.map((g) => (
        <div className="mgroup" key={g.group}>
          <div className="pgroup-label">{g.group}</div>
          {g.fields.map((f) => (
            <ConstRow key={f.name} spec={f}
                      value={props.values[f.name]} def={props.defaults[f.name]}
                      onEdit={props.onEdit} />
          ))}
        </div>
      ))}
    </div>
  );
}

function ConstRow(props: {
  spec: MappingFieldSpec;
  value: unknown;
  def: unknown;
  onEdit: (field: string, value: unknown) => void;
}) {
  const { spec, value, def, onEdit } = props;
  const current = value ?? def;
  const changed = JSON.stringify(current) !== JSON.stringify(def);
  return (
    <div className={`mrow${changed ? " changed" : ""}`}>
      <span className="mrow-name" title={changed ? `default ${JSON.stringify(def)}` : spec.name}>
        {spec.name}
      </span>
      {spec.kind === "range" ? (
        <div className="mrow-range">
          <NumberField value={Number((current as number[])[0])} step={spec.step}
                       onCommit={(n) => onEdit(spec.name, [n, (current as number[])[1]])} />
          <NumberField value={Number((current as number[])[1])} step={spec.step}
                       onCommit={(n) => onEdit(spec.name, [(current as number[])[0], n])} />
        </div>
      ) : (
        <NumberField value={Number(current)} step={spec.step}
                     onCommit={(n) => onEdit(spec.name, n)} />
      )}
      <button className={`revert${changed ? "" : " hidden"}`} title="reset to default"
              onClick={() => onEdit(spec.name, def)}>↺</button>
    </div>
  );
}

// Commits on blur / Enter (not per keystroke); re-syncs to the incoming value
// when it changes externally (recall / reset / apply) unless being edited.
function NumberField(props: { value: number; step: number; onCommit: (v: number) => void }) {
  const [text, setText] = useState(String(props.value));
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(String(props.value));
  }, [props.value]);
  const commit = () => {
    const n = Number(text);
    if (text.trim() !== "" && Number.isFinite(n)) props.onCommit(n);
    else setText(String(props.value)); // revert a blank / non-numeric entry (Number("")===0)
  };
  return (
    <input className="mfield mono" type="number" step={props.step} value={text}
           onFocus={() => { focused.current = true; }}
           onChange={(e) => setText(e.target.value)}
           onBlur={() => { focused.current = false; commit(); }}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}
