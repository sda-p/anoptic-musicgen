import { useEffect, useState } from "react";
import { useMain } from "../store";
import { api, deletePreset, exportFile, listPresets, loadPreset, savePreset } from "../ws";
import { AutomationTimeline } from "./AutomationTimeline";

// Phase 7: sessions & automation. Save/recall the whole session as a named
// preset (exact same-seed A/B by ear), draw the affect automation, jump the
// deterministic engine to any bar, and bounce the current config to WAV/MIDI.
export function SessionsTab() {
  const { running, startBar, seed } = useMain();
  const [presets, setPresets] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [bars, setBars] = useState(32);
  const [seekBar, setSeekBar] = useState(String(startBar));
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { listPresets().then(setPresets).catch(() => {}); }, []);
  useEffect(() => { setSeekBar(String(startBar)); }, [startBar]);

  const flash = (m: string) => { setStatus(m); window.setTimeout(() => setStatus(null), 4000); };

  const onSave = async () => {
    const n = name.trim();
    if (!n) return;
    try { setPresets(await savePreset(n)); flash(`saved "${n}"`); setName(""); }
    catch (e) { flash(String((e as Error).message)); }
  };
  const onLoad = async (n: string) => {
    try { await loadPreset(n); flash(`loaded "${n}"`); }
    catch (e) { flash(String((e as Error).message)); }
  };
  const onDelete = async (n: string) => { setPresets(await deletePreset(n)); };

  const onExport = async (kind: "wav" | "midi") => {
    setBusy(true);
    setStatus(`rendering ${kind.toUpperCase()}…`);
    try { await exportFile(kind, bars); flash(`${kind.toUpperCase()} downloaded`); }
    catch (e) { flash(String((e as Error).message)); }
    finally { setBusy(false); }
  };

  const onSeek = () => {
    const n = Number(seekBar);
    if (Number.isFinite(n)) api.seek(Math.max(0, Math.round(n)));
  };

  return (
    <div className="sessions">
      <div className="sessions-cols">
        <section className="sessions-block">
          <div className="block-title">session presets</div>
          <div className="preset-save">
            <input
              placeholder="preset name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onSave()}
            />
            <button className="btn" onClick={onSave} disabled={!name.trim()}>save</button>
          </div>
          <ul className="preset-list">
            {presets.length === 0 && <li className="empty">no presets yet</li>}
            {presets.map((n) => (
              <li key={n}>
                <span className="preset-name mono">{n}</span>
                <button className="btn btn-small" onClick={() => onLoad(n)}>load</button>
                <button className="btn btn-small btn-danger" onClick={() => onDelete(n)}>×</button>
              </li>
            ))}
          </ul>
          <div className="hint">
            captures seed, affect, overrides, mapping, console &amp; automation —
            load two and A/B them at the same seed.
          </div>
        </section>

        <section className="sessions-block">
          <div className="block-title">jump to bar</div>
          <div className="seek-row">
            <input
              className="mono"
              type="number"
              min={0}
              value={seekBar}
              onChange={(e) => setSeekBar(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onSeek()}
            />
            <button className="btn" onClick={onSeek}>seek</button>
          </div>
          <div className="hint">
            play resumes from this bar (deterministic warm-up, brief gap while
            running). now: <span className="mono">bar {startBar}</span>
          </div>

          <div className="block-title" style={{ marginTop: "16px" }}>export</div>
          <div className="export-row">
            <label className="bars-in">
              bars
              <input
                className="mono"
                type="number"
                min={1}
                max={512}
                value={bars}
                onChange={(e) => setBars(Math.max(1, Math.min(512, Number(e.target.value) || 1)))}
              />
            </label>
            <button className="btn" onClick={() => onExport("wav")} disabled={busy || running}>WAV</button>
            <button className="btn" onClick={() => onExport("midi")} disabled={busy || running}>MIDI</button>
          </div>
          <div className="hint">
            {running ? "stop playback to export (one audio graph)"
              : `offline bounce of seed ${seed} from bar 0`}
          </div>
        </section>
      </div>

      <section className="sessions-block">
        <div className="block-title">affect automation</div>
        <AutomationTimeline />
      </section>

      {status && <div className="sessions-status">{status}</div>}
    </div>
  );
}
