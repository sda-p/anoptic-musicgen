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
  const cad64 = Boolean(s.perform.cadential_64);
  const periods = Boolean(s.perform.periods);
  const hyper = Boolean(s.perform.hypermeter);
  const bassInv = Boolean(s.perform.bass_inversions);
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
      <label className={`toggle toggle-sub ${periods ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={periods}
          onChange={(e) => api.setPerform({ periods: e.target.checked })}
        />
        {periods
          ? "periods on · question phrases answered — half cadence, then the same opening resolved"
          : "periods off · phrases chain without pairing"}
      </label>
      <label className={`toggle toggle-sub ${cad64 ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={cad64}
          onChange={(e) => api.setPerform({ cadential_64: e.target.checked })}
        />
        {cad64
          ? "cadential 6/4 on · authentic cadences arrive prepared (I64 → V → I)"
          : "cadential 6/4 off · cadences correct but unprepared"}
      </label>
      <label className={`toggle toggle-sub ${hyper ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={hyper}
          onChange={(e) => api.setPerform({ hypermeter: e.target.checked })}
        />
        {hyper
          ? "hypermeter on · bars weighted within the group, mid-phrase fills"
          : "hypermeter off · all bars weigh the same"}
      </label>
      <label className={`toggle toggle-sub ${bassInv ? "on" : ""}`}>
        <input
          type="checkbox"
          checked={bassInv}
          onChange={(e) => api.setPerform({ bass_inversions: e.target.checked })}
        />
        {bassInv
          ? "bass planning on · stepwise bass via inversions, lament grounds on odd buildups"
          : "bass planning off · the bass reports roots"}
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
