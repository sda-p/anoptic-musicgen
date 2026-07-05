import { useMain } from "../store";

// Where we are in the phrase — the iMUSE structure made visible. The last two
// cells are the cadence zone (pre-cadence, cadence); the current bar is lit.
export function PhraseStrip() {
  const s = useMain();
  if (s.bar == null) return null;
  const n = s.phraseBars || 8;
  const pos = s.bar % n;
  const slot = s.context?.cadence_slot ?? "";
  const policy = s.context?.cadence_policy ?? "";
  return (
    <div className="phrase-strip">
      <span className="phrase-label">phrase</span>
      <div className="phrase-cells">
        {Array.from({ length: n }, (_, i) => (
          <span key={i}
                className={`phrase-cell${i === pos ? " here" : ""}${i >= n - 2 ? " cadence-zone" : ""}`} />
        ))}
      </div>
      {slot && <span className="phrase-slot">{slot}{policy ? ` · ${policy}` : ""}</span>}
    </div>
  );
}
