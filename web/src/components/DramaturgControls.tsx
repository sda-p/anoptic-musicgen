import { useMain } from "../store";
import { api } from "../ws";
import { ConstantsGrid } from "./ConstantsGrid";

// Live controls for the tension-debt ledger (§5.8, M13/M14/M15): an enable toggle,
// the `earned_dissonance` sub-toggle (the M14 A/B — obligation-bearing suspensions,
// pedals, appoggiaturas, secondary dominants vs. ambient colour only), the
// `motif_lifecycle` sub-toggle (M15 — a persistent signature introduced→developed→
// completed, landing whole on a spend vs. a disposable motif per phrase), plus the
// tunable knobs (`leniency` is the headline — how strict the release bar is vs. how
// far overdue pressure overrides it). Hot-swapped between bars, no rebuild, so it is
// all tunable by ear. Off by default, which is byte-identical to no dramaturg.
export function DramaturgControls() {
  const s = useMain();
  const enabled = Boolean(s.dramaturg.enabled);
  const earned = Boolean(s.dramaturg.earned_dissonance);
  const lifecycle = Boolean(s.dramaturg.motif_lifecycle);
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
      {enabled && (
        <>
          <label className={`toggle toggle-sub ${earned ? "on" : ""}`}>
            <input
              type="checkbox"
              checked={earned}
              onChange={(e) => api.setDramaturg({ earned_dissonance: e.target.checked })}
            />
            {earned
              ? "earned dissonance on · suspensions · pedals · secondary dominants"
              : "earned dissonance off · ambient colour only"}
          </label>
          <label className={`toggle toggle-sub ${lifecycle ? "on" : ""}`}>
            <input
              type="checkbox"
              checked={lifecycle}
              onChange={(e) => api.setDramaturg({ motif_lifecycle: e.target.checked })}
            />
            {lifecycle
              ? "motif lifecycle on · a signature introduced → developed → completed on the spend"
              : "motif lifecycle off · a disposable motif per phrase"}
          </label>
          {s.dramaturgUi.length > 0 && (
            <ConstantsGrid
              ui={s.dramaturgUi}
              values={s.dramaturg}
              defaults={s.dramaturgDefaults}
              onEdit={(f, v) => api.setDramaturg({ [f]: v as number })}
            />
          )}
        </>
      )}
    </div>
  );
}
