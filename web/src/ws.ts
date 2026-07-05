import { mainStore, meterStore } from "./store";
import type { Affect, ServerMessage } from "./protocol";

// One WebSocket to the FastAPI service; auto-reconnects. Served from the same
// origin whether the page comes from FastAPI (prod) or the Vite dev proxy.
let socket: WebSocket | null = null;
let reconnect: ReturnType<typeof setTimeout> | undefined;
const TRACE_LIMIT = 250;

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
      });
      break;
    case "snapshot":
      mainStore.set({
        running: msg.running,
        seed: msg.seed,
        snapshotAffect: msg.affect,
        pinned: msg.pinned,
      });
      break;
    case "bar": {
      const trace = [...mainStore.get().trace, ...msg.trace].slice(-TRACE_LIMIT);
      mainStore.set({
        context: msg.context,
        params: msg.params,
        mapped: msg.mapped,
        engineAffect: msg.affect,
        bar: msg.bar,
        trace,
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
};
