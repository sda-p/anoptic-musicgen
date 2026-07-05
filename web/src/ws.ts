import { mainStore, meterStore } from "./store";
import type { Affect, ServerMessage } from "./protocol";

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
};
