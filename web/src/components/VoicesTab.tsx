import { InstrumentsPicker } from "./InstrumentsPicker";
import { ConsoleEditor } from "./ConsoleEditor";

// Voice & mix tuning: the per-layer patch picker (live) above the console
// structural tuner (rebuild) — the two halves of the live-vs-rebuild split.
export function VoicesTab() {
  return (
    <div className="voices-tab">
      <InstrumentsPicker />
      <ConsoleEditor />
    </div>
  );
}
