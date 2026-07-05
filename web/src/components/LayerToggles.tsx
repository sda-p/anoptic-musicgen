import { useMain } from "../store";
import { api } from "../ws";

const FALLBACK = ["pad", "bass", "melody", "arp", "perc"];

// The `layers` override as a row of toggles. Follow => the mapper gates layers
// by energy (buttons show the live set, disabled). Pin => toggle them by hand.
export function LayerToggles() {
  const s = useMain();
  const all = s.schema?.layers ?? FALLBACK;
  const pinned = "layers" in s.pinned;
  const active: string[] = pinned
    ? ((s.pinned.layers as string[]) ?? [])
    : (s.params?.layers ?? []);

  const toggle = (layer: string) => {
    const set = new Set(active);
    if (set.has(layer)) set.delete(layer);
    else set.add(layer);
    api.setOverride("layers", all.filter((l) => set.has(l)));
  };

  return (
    <div className={`layers-ctl${pinned ? " is-pinned" : ""}`}>
      <span className="prow-name">layers</span>
      <div className="layer-btns">
        {all.map((l) => (
          <button key={l} disabled={!pinned}
                  className={`layer-btn${active.includes(l) ? " on" : ""}`}
                  onClick={() => toggle(l)}>
            {l}
          </button>
        ))}
      </div>
      <button className={`pin-btn${pinned ? " on" : ""}`}
              onClick={() => (pinned ? api.clearOverride("layers") : api.setOverride("layers", active))}>
        {pinned ? "pinned" : "auto"}
      </button>
    </div>
  );
}
