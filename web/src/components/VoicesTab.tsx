import { InstrumentsPicker } from "./InstrumentsPicker";
import { SamplerControl } from "./SamplerControl";
import { ConsoleEditor } from "./ConsoleEditor";

// Voice & mix tuning: the per-layer patch picker (live) and the sampler loader
// above the console structural tuner (rebuild) — the two halves of the
// live-vs-rebuild split.
export function VoicesTab() {
  return (
    <div className="voices-tab">
      <InstrumentsPicker />
      <SamplerControl />
      <ConsoleEditor />
    </div>
  );
}
