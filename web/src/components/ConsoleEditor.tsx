import { useState } from "react";
import { useMain } from "../store";
import { api } from "../ws";
import { ConstantsGrid } from "./ConstantsGrid";

// The console (voice/mix) tuner. These are STRUCTURAL params baked into the
// audio graph, so unlike the mapped DSP sends they can't glide — edits are
// staged locally and applied together, rebuilding the console (a brief gap).
export function ConsoleEditor() {
  const s = useMain();
  const [pending, setPending] = useState<Record<string, unknown>>({});
  if (s.consoleUi.length === 0) {
    return <div className="pgrid-empty">waiting for schema…</div>;
  }
  const values = { ...s.console, ...pending };
  const count = Object.keys(pending).length;
  const apply = () => {
    api.setConsole(pending);
    setPending({});
  };
  return (
    <div className="meditor">
      <div className="meditor-bar">
        <span className="meditor-hint">
          structural voice/mix params — <b>apply</b> rebuilds the console (a brief gap)
        </span>
        <div className="ab-slots">
          <span className="dirty-note">{count ? `${count} unapplied` : "in sync"}</span>
          <button className="btn-sm" disabled={!count} onClick={() => setPending({})}>discard</button>
          <button className="btn-sm btn-apply" disabled={!count} onClick={apply}>apply · rebuild</button>
        </div>
      </div>
      <ConstantsGrid ui={s.consoleUi} values={values} defaults={s.consoleDefaults}
                     onEdit={(field, value) => setPending((p) => ({ ...p, [field]: value }))} />
    </div>
  );
}
