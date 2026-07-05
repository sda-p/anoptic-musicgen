import { useMain } from "../store";
import { api } from "../ws";
import { ConstantsGrid } from "./ConstantsGrid";

// Live controls for the tension-debt ledger (§5.8, M13): an enable toggle plus
// the tunable knobs (`leniency` is the headline — how strict the release bar is
// vs. how far overdue pressure overrides it). Hot-swapped between bars, no
// rebuild, so the withholding/payoff behaviour is tunable by ear. Off by default,
// which is byte-identical to no dramaturg.
export function DramaturgControls() {
  const s = useMain();
  const enabled = Boolean(s.dramaturg.enabled);
  return (
    <div className="dramaturg-ctl">
      <div className="dramaturg-head">
        <label className={`toggle ${enabled ? "on" : ""}`}>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => api.setDramaturg({ enabled: e.target.checked })}
          />
          {enabled ? "dramaturg on · banks tension, sizes payoffs" : "dramaturg off"}
        </label>
        <span className="prow-boundary" title="hot-swapped live, between bars">live</span>
      </div>
      {enabled && s.dramaturgUi.length > 0 && (
        <ConstantsGrid
          ui={s.dramaturgUi}
          values={s.dramaturg}
          defaults={s.dramaturgDefaults}
          onEdit={(f, v) => api.setDramaturg({ [f]: v as number })}
        />
      )}
    </div>
  );
}
