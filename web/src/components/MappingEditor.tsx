import { useMain } from "../store";
import { api } from "../ws";
import { ConstantsGrid } from "./ConstantsGrid";
import { DramaturgControls } from "./DramaturgControls";
import { PerformControls } from "./PerformControls";

const SLOTS = ["A", "B"];

// The live MappingTable heuristics editor. Editing a constant hot-swaps the
// whole (frozen) table at the next bar — deterministic per (seed, bar), so A/B
// of a heuristic change at one seed is exact (store A, edit, store B, restart
// the transport to hear each from bar 0).
export function MappingEditor() {
  const s = useMain();
  if (s.mappingUi.length === 0) {
    return <div className="pgrid-empty">waiting for schema…</div>;
  }
  return (
    <div className="meditor">
      <DramaturgControls />
      <PerformControls />
      <div className="meditor-bar">
        <span className="meditor-hint">
          edit the affect→music heuristics — each change hot-swaps at the next bar
        </span>
        <div className="ab-slots">
          {SLOTS.map((slot) => (
            <span className="ab-slot" key={slot}>
              <button className="btn-sm" onClick={() => api.storeMapping(slot)}
                      title={`store the current table in slot ${slot}`}>store {slot}</button>
              <button className="btn-sm" disabled={!s.slots.includes(slot)}
                      onClick={() => api.recallMapping(slot)}
                      title={`recall slot ${slot} into the live table`}>recall {slot}</button>
            </span>
          ))}
          <button className="btn-sm btn-reset" onClick={() => api.resetMapping()}>reset all</button>
        </div>
      </div>
      <ConstantsGrid ui={s.mappingUi} values={s.mapping} defaults={s.mappingDefaults}
                     onEdit={api.setMapping} />
    </div>
  );
}
