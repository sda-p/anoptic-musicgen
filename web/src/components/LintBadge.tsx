import { useMain } from "../store";

// Live theory-lint status of the current bar — the same linter the offline
// renders must pass, run on a sliding window. Green while clean; a manual
// override or heuristic edit that breaks theory turns it red with details.
export function LintBadge() {
  const s = useMain();
  if (!s.running) return null;
  const { clean, violations } = s.lint;
  return (
    <div className={`lint-badge${clean ? " clean" : " dirty"}`}
         title={violations.map((v) => `[${v.rule}] ${v.message}`).join("\n")}>
      {clean
        ? "✓ theory-clean"
        : `⚠ ${violations.length} violation${violations.length > 1 ? "s" : ""}`}
    </div>
  );
}
