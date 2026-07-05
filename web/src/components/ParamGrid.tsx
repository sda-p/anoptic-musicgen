import { useMain } from "../store";
import { LayerToggles } from "./LayerToggles";
import { ParamRow } from "./ParamRow";

// The follow/pin grid: layer toggles on top, then the Tier-2 params grouped by
// the affect lever that primarily drives each.
export function ParamGrid() {
  const s = useMain();
  if (s.paramUi.length === 0) {
    return <div className="pgrid-empty">waiting for schema…</div>;
  }
  return (
    <div className="pgrid">
      <LayerToggles />
      <div className="pgrid-cols">
        {s.paramUi.map((g) => (
          <div className="pgroup" key={g.group}>
            <div className="pgroup-label">{g.label}</div>
            {g.params.map((p) => <ParamRow key={p.name} spec={p} />)}
          </div>
        ))}
      </div>
    </div>
  );
}
