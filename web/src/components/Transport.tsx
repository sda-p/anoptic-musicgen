import { useEffect, useState } from "react";
import { useMain } from "../store";
import { api } from "../ws";

// Play/stop the engine and set the seed. Reseed takes effect on the next
// start (deterministic per (seed, bar)), so it's hinted while running.
export function Transport() {
  const { running, seed } = useMain();
  const [seedInput, setSeedInput] = useState(String(seed));
  // re-sync when the seed changes server-side (e.g. a preset load)
  useEffect(() => { setSeedInput(String(seed)); }, [seed]);

  const commitSeed = () => {
    const n = Number(seedInput);
    if (seedInput.trim() !== "" && Number.isFinite(n)) api.reseed(Math.round(n));
    else setSeedInput(String(seed)); // revert a blank / non-numeric entry
  };

  return (
    <div className="transport">
      {running ? (
        <button className="btn btn-stop" onClick={api.stop}>
          ■ stop
        </button>
      ) : (
        <button className="btn btn-play" onClick={api.start}>
          ▶ play
        </button>
      )}
      <label className="seed">
        seed
        <input
          className="mono"
          value={seedInput}
          onChange={(e) => setSeedInput(e.target.value)}
          onBlur={commitSeed}
          onKeyDown={(e) => e.key === "Enter" && commitSeed()}
          inputMode="numeric"
        />
      </label>
      {running && <span className="hint">seed applies on next start</span>}
    </div>
  );
}
