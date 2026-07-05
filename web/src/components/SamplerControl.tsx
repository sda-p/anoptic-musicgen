import { useRef, useState } from "react";
import { useMain } from "../store";

// Load an audio file into the sampler ("keys") melody voice, replacing the
// synth bell. Upload is multipart REST (not the WS); on success the server
// rebuilds the console and broadcasts a snapshot, so `s.sample` updates. `root`
// is the MIDI note the file plays at its natural rate (repitched from there).
export function SamplerControl() {
  const s = useMain();
  const [root, setRoot] = useState(72);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const loaded = s.sample.name;

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setBusy(true);
    setErr("");
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("root", String(root));
      const res = await fetch("/api/sample", { method: "POST", body });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setErr(j.error || `upload failed (${res.status})`);
      } else if (fileRef.current) {
        fileRef.current.value = "";
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sampler-ctl">
      <div className="instruments-head">
        <span className="prow-name">sampler · "keys" voice</span>
        <span className="prow-boundary" title="loading a sample rebuilds the console">rebuild</span>
      </div>
      <div className="sampler-row">
        <span className="sampler-current mono">{loaded || "synth bell (default)"}</span>
        {loaded && (
          <button className="btn-sm" onClick={() => void fetch("/api/sample/clear", { method: "POST" })}>
            clear
          </button>
        )}
      </div>
      <div className="sampler-row">
        <input ref={fileRef} type="file" className="sampler-file"
               accept="audio/*,.wav,.flac,.aiff,.aif,.ogg" />
        <label className="sampler-root">
          root
          <input className="mfield mono" type="number" min={0} max={127} value={root}
                 onChange={(e) => setRoot(Number(e.target.value))} />
        </label>
        <button className="btn-sm btn-apply" disabled={busy} onClick={upload}>
          {busy ? "loading…" : "load"}
        </button>
      </div>
      {err && <div className="sampler-err mono">{err}</div>}
    </div>
  );
}
