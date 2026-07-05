import { useSyncExternalStore } from "react";
import type { Affect, BarContext, Params, SchemaMsg } from "./protocol";

// A minimal external store: replace-and-notify. Two instances keep the 30 fps
// meter feed off the per-bar telemetry store, so meter frames never re-render
// the control/telemetry panels.
function createStore<T extends object>(initial: T) {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set: (patch: Partial<T>) => {
      state = { ...state, ...patch };
      listeners.forEach((l) => l());
    },
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
  };
}

const DEFAULT_AFFECT: Affect = { valence: 0.3, energy: 0.5, tension: 0.45 };

export interface MainState {
  connected: boolean;
  running: boolean;
  seed: number;
  snapshotAffect: Affect; // server mirror (seeds the controls)
  engineAffect: Affect; // per-bar reported affect (the pad/fader "ghost")
  context: BarContext | null;
  params: Params | null;
  pinned: string[];
  bar: number | null;
  trace: string[];
  schema: SchemaMsg | null;
  error: string | null;
}

export const mainStore = createStore<MainState>({
  connected: false,
  running: false,
  seed: 42,
  snapshotAffect: DEFAULT_AFFECT,
  engineAffect: DEFAULT_AFFECT,
  context: null,
  params: null,
  pinned: [],
  bar: null,
  trace: [],
  schema: null,
  error: null,
});

export function useMain(): MainState {
  return useSyncExternalStore(mainStore.subscribe, mainStore.get);
}

export interface MeterState {
  level: number;
  cpu: number;
  bars: number;
}

export const meterStore = createStore<MeterState>({ level: 0, cpu: 0, bars: 0 });

export function useMeter(): MeterState {
  return useSyncExternalStore(meterStore.subscribe, meterStore.get);
}
