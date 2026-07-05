import { useState } from "react";
import { ParamGrid } from "./ParamGrid";
import { MappingEditor } from "./MappingEditor";
import { VoicesTab } from "./VoicesTab";

type Tab = "params" | "heuristics" | "voices";

const TABS: { id: Tab; label: string }[] = [
  { id: "params", label: "parameters · follow / pin" },
  { id: "heuristics", label: "heuristics · mapping table" },
  { id: "voices", label: "voices · mix" },
];

// The dense lower half as tabs, so the layout stays legible: the follow/pin
// grid (Phase 3), the live MappingTable editor (Phase 4), and voice/mix tuning
// (Phase 5).
export function BottomPanel() {
  const [tab, setTab] = useState<Tab>("params");
  return (
    <section className="panel bottom-panel">
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.id} className={`tab${tab === t.id ? " active" : ""}`}
                  onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>
      <div className="bottom-body">
        {tab === "params" ? <ParamGrid /> : tab === "heuristics" ? <MappingEditor /> : <VoicesTab />}
      </div>
    </section>
  );
}
