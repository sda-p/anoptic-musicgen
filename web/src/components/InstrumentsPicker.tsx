import { useMain } from "../store";
import { api } from "../ws";

// Per-layer patch selection — the `instruments` override (deferred from the
// Phase 3 grid). Follow => the mapper swaps patches by energy tier; pin => pick
// them by hand. Swaps land on the phrase and take effect at the next note-on.
const LAYERS = ["pad", "bass", "melody", "arp"]; // perc has no instrument tier

export function InstrumentsPicker() {
  const s = useMain();
  const pinned = "instruments" in s.pinned;
  const current: [string, string][] = pinned
    ? ((s.pinned.instruments as [string, string][]) ?? [])
    : (s.params?.instruments ?? []);
  const currentMap = new Map(current);
  const patchesByLayer = s.schema?.patches_by_layer ?? {};

  const setPatch = (layer: string, patch: string) => {
    const next = LAYERS.map((l) =>
      [l, l === layer ? patch : (currentMap.get(l) ?? patchesByLayer[l]?.[0] ?? "")] as [string, string],
    );
    api.setOverride("instruments", next);
  };

  return (
    <div className="instruments">
      <div className="instruments-head">
        <span className="prow-name">instruments</span>
        <span className="prow-boundary" title="instrument swaps land on the phrase">phrase</span>
        <button className={`pin-btn${pinned ? " on" : ""}`}
                onClick={() => (pinned ? api.clearOverride("instruments") : api.setOverride("instruments", current))}>
          {pinned ? "pinned" : "auto"}
        </button>
      </div>
      <div className="instruments-grid">
        {LAYERS.map((layer) => (
          <label className="instrument-row" key={layer}>
            <span className="instrument-layer">{layer}</span>
            <select className="enum-select" disabled={!pinned}
                    value={currentMap.get(layer) ?? ""}
                    onChange={(e) => setPatch(layer, e.target.value)}>
              {(patchesByLayer[layer] ?? []).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
        ))}
      </div>
    </div>
  );
}
