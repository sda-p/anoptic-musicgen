import { mainStore, meterStore } from "./store";
import type { Affect, AutomationPoint, AutomationTrack, ServerMessage } from "./protocol";

// One WebSocket to the FastAPI service; auto-reconnects. Served from the same
// origin whether the page comes from FastAPI (prod) or the Vite dev proxy.
let socket: WebSocket | null = null;
let reconnect: ReturnType<typeof setTimeout> | undefined;
const TRACE_LIMIT = 250;
const ROLL_BARS = 8;

export function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/ws`);
  socket.onopen = () => mainStore.set({ connected: true, error: null });
  socket.onmessage = (ev) => handle(JSON.parse(ev.data) as ServerMessage);
  socket.onclose = () => {
    mainStore.set({ connected: false });
    if (!reconnect) {
      reconnect = setTimeout(() => {
        reconnect = undefined;
        connect();
      }, 1000);
    }
  };
}

function handle(msg: ServerMessage): void {
  switch (msg.type) {
    case "schema":
      mainStore.set({
        schema: msg,
        paramUi: msg.param_ui,
        paramDefaults: Object.fromEntries(msg.params.map((p) => [p.name, p.default])),
        mappingUi: msg.mapping_ui,
        mappingDefaults: Object.fromEntries(
          msg.mapping_ui.flatMap((g) => g.fields.map((f) => [f.name, f.default])),
        ),
        consoleUi: msg.console_ui,
        consoleDefaults: Object.fromEntries(
          msg.console_ui.flatMap((g) => g.fields.map((f) => [f.name, f.default])),
        ),
        phraseBars: msg.phrase_bars,
      });
      break;
    case "snapshot":
      mainStore.set({
        running: msg.running,
        seed: msg.seed,
        snapshotAffect: msg.affect,
        pinned: msg.pinned,
        mapping: msg.mapping,
        slots: msg.slots,
        console: msg.console,
        sample: msg.sample,
        startBar: msg.start_bar,
        automation: msg.automation,
      });
      break;
    case "bar": {
      const st = mainStore.get();
      const trace = [...st.trace, ...msg.trace].slice(-TRACE_LIMIT);
      // reset the roll when the engine restarts (bar number goes backwards)
      const reset = st.roll.length > 0 && msg.bar <= st.roll[st.roll.length - 1].bar;
      const roll = (reset ? [] : st.roll)
        .concat({ bar: msg.bar, events: msg.events, rawEvents: msg.raw_events })
        .slice(-ROLL_BARS);
      mainStore.set({
        context: msg.context,
        params: msg.params,
        mapped: msg.mapped,
        engineAffect: msg.affect,
        bar: msg.bar,
        trace,
        roll,
        lint: msg.lint,
      });
      break;
    }
    case "meter":
      meterStore.set({ level: msg.level, cpu: msg.cpu, bars: msg.bars });
      break;
    case "error":
      mainStore.set({ error: msg.error });
      break;
  }
}

function send(msg: object): void {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg));
}

// Control surface. Phase 3+ extends this with setOverride / clearOverride /
// setMapping / requestKey; the skeleton needs only transport, affect, seed.
export const api = {
  start: () => send({ type: "transport", action: "start" }),
  stop: () => send({ type: "transport", action: "stop" }),
  setAffect: (a: Partial<Affect>, urgent = false) => send({ type: "set_affect", ...a, urgent }),
  reseed: (seed: number) => send({ type: "reseed", seed }),
  // pin a Tier-2 param (optimistic: update the store now, the server snapshot confirms)
  setOverride: (name: string, value: unknown) => {
    mainStore.set({ pinned: { ...mainStore.get().pinned, [name]: value } });
    send({ type: "set_override", name, value });
  },
  clearOverride: (name: string) => {
    const pinned = { ...mainStore.get().pinned };
    delete pinned[name];
    mainStore.set({ pinned });
    send({ type: "clear_override", name });
  },
  // hot-edit a MappingTable constant (optimistic; the swap lands at the next bar)
  setMapping: (field: string, value: unknown) => {
    mainStore.set({ mapping: { ...mainStore.get().mapping, [field]: value } });
    send({ type: "set_mapping", field, value });
  },
  resetMapping: () => send({ type: "reset_mapping" }),
  storeMapping: (slot: string) => send({ type: "mapping_store", slot }),
  recallMapping: (slot: string) => send({ type: "mapping_recall", slot }),
  // structural console change: rebuilds the audio graph (a brief gap)
  setConsole: (fields: Record<string, unknown>) => send({ type: "set_console", fields }),
  // drawable affect automation (optimistic; the server echoes a snapshot)
  setAutomation: (patch: Partial<AutomationTrack>) => {
    mainStore.set({ automation: { ...mainStore.get().automation, ...patch } });
    send({ type: "set_automation", ...patch });
  },
  // jump-to-bar: restarts the running engine warmed to this deterministic bar
  seek: (bar: number) => send({ type: "seek", bar }),
};

// Presets + export ride REST (file I/O), not the WebSocket. Each returns the
// refreshed preset list where relevant so the sessions tab can re-render.
export async function listPresets(): Promise<string[]> {
  const r = await fetch("/api/presets");
  return (await r.json()).presets ?? [];
}

export async function savePreset(name: string): Promise<string[]> {
  const r = await fetch("/api/preset", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const j = await r.json();
  if (!j.ok) throw new Error(j.error ?? "save failed");
  return j.presets ?? [];
}

export async function loadPreset(name: string): Promise<void> {
  const r = await fetch("/api/preset/load", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error((await r.json()).error ?? "load failed");
}

export async function deletePreset(name: string): Promise<string[]> {
  const r = await fetch("/api/preset/delete", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return (await r.json()).presets ?? [];
}

// Fetch the export as a blob so a 409 (playing) / 500 surfaces as a message
// instead of downloading an error body; on success, trigger a browser download.
export async function exportFile(kind: "wav" | "midi", bars: number): Promise<void> {
  const r = await fetch(`/api/export?kind=${kind}&bars=${bars}`);
  if (!r.ok) {
    let msg = `export failed (${r.status})`;
    try { msg = (await r.json()).error ?? msg; } catch { /* non-JSON body */ }
    throw new Error(msg);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `musicgen-${bars}bars.${kind === "midi" ? "mid" : "wav"}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export type { AutomationPoint };
