import { useMain } from "../store";
import { api } from "../ws";
import { ConstantsGrid } from "./ConstantsGrid";

// Live controls for the performed surface (REFINEMENT_PLAN wave A / PLANS M19):
// `shaping` inserts the deterministic Perform modifiers (velocity hairpin cresting
// at the melodic apex, contour-tracking loudness, agogic phrase-open downbeats, a
// luftpause before phrase downbeats, lay-back/push by density) plus the cadence
// micro-ritardando whose depth is the one tunable knob; `phrase_groove` pins the
// perc/arp pattern draws per phrase (A2 — pattern identity as a contract, fills
// stay per-bar); `plan_apex` plans one melodic peak per phrase (A4 — every other
// bar stays below it, gap-fill descent for free). Hot-swapped between bars, no
// rebuild. All off by default, which is byte-identical to the unshaped engine.
export function PerformControls() {
  const s = useMain();
  const shaping = Boolean(s.perform.shaping);
  const groove = Boolean(s.perform.phrase_groove);
  const apex = Boolean(s.perform.plan_apex);
  const counterpoint = Boolean(s.perform.counterpoint);
  return (
    <div className="dramaturg-ctl">
      <div className="dramaturg-head">
        <label className={`toggle ${shaping ? "on" : ""}`}>
          <input
            type="checkbox"
            checked={shaping}
            onChange={(e) => api.setPerform({ shaping: e.target.checked })}
          />
          {shaping
            ? "performance shaping on · hairpin · luftpause · agogic · lay-back · cadence rit"
            : "performance shaping off · sequenced, not played"}
        </label>
        <span className="prow-boundary" title="hot-swapped live, between bars">live</span>
      </div>
      <label className={`toggle toggle-sub ${groove ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={groove}
          onChange={(e) => api.setPerform({ phrase_groove: e.target.checked })}
        />
        {groove
          ? "phrase groove on · perc/arp pattern pinned per phrase, fills stay free"
          : "phrase groove off · pattern draws re-roll every bar"}
      </label>
      <label className={`toggle toggle-sub ${apex ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={apex}
          onChange={(e) => api.setPerform({ plan_apex: e.target.checked })}
        />
        {apex
          ? "apex planning on · one melodic peak per phrase, hairpin crests with it"
          : "apex planning off · unplanned contour"}
      </label>
      <label className={`toggle toggle-sub ${counterpoint ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={counterpoint}
          onChange={(e) => api.setPerform({ counterpoint: e.target.checked })}
        />
        {counterpoint
          ? "outer-voice counterpoint on · no parallel 5ths/8ves, contrary cadences"
          : "outer-voice counterpoint off · the melody-bass frame is unguarded"}
      </label>
      {shaping && s.performUi.length > 0 && (
        <ConstantsGrid
          ui={s.performUi}
          values={s.perform}
          defaults={s.performDefaults}
          onEdit={(f, v) => api.setPerform({ [f]: v as number })}
        />
      )}
    </div>
  );
}
