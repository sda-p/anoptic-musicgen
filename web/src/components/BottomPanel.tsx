import { useState } from "react";
import { ParamGrid } from "./ParamGrid";
import { MappingEditor } from "./MappingEditor";
import { VoicesTab } from "./VoicesTab";
import { PianoRoll } from "./PianoRoll";
import { SessionsTab } from "./SessionsTab";

type Tab = "params" | "heuristics" | "voices" | "inspect" | "sessions";

const TABS: { id: Tab; label: string }[] = [
  { id: "params", label: "parameters · follow / pin" },
  { id: "heuristics", label: "heuristics · mapping table" },
  { id: "voices", label: "voices · mix" },
  { id: "inspect", label: "inspect · piano-roll" },
  { id: "sessions", label: "sessions · automation" },
];

// The dense lower half as tabs, so the layout stays legible: the follow/pin
// grid (Phase 3), the live MappingTable editor (Phase 4), voice/mix tuning
// (Phase 5), the piano-roll inspector (Phase 6), and sessions & automation
// (Phase 7).
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
        {tab === "params" ? <ParamGrid />
          : tab === "heuristics" ? <MappingEditor />
          : tab === "voices" ? <VoicesTab />
          : tab === "inspect" ? <PianoRoll />
          : <SessionsTab />}
      </div>
    </section>
  );
}
