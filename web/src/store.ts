import { useSyncExternalStore } from "react";
import type {
  Affect, AutomationTrack, BarContext, EventDef, Lint, MappingGroup, ParamGroup, Params, SchemaMsg,
} from "./protocol";

export interface RollBar {
  bar: number;
  events: EventDef[];
  rawEvents: EventDef[];
}

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
  mapped: Record<string, number | string>; // mapper targets (follow/pin ghost)
  pinned: Record<string, unknown>; // name -> pinned value
  paramUi: ParamGroup[];
  paramDefaults: Record<string, unknown>; // per-param default (fallback when stopped)
  mapping: Record<string, unknown>; // live MappingTable constant values
  mappingUi: MappingGroup[];
  mappingDefaults: Record<string, unknown>; // per-constant default (diff / revert)
  slots: string[]; // filled A/B mapping snapshot slots
  console: Record<string, number>; // applied ConsoleConfig numeric values
  consoleUi: MappingGroup[];
  consoleDefaults: Record<string, unknown>;
  dramaturg: Record<string, number | boolean>; // live tension-debt-ledger config (§5.8)
  dramaturgUi: MappingGroup[];
  dramaturgDefaults: Record<string, unknown>;
  perform: Record<string, number | boolean>; // performed surface (REFINEMENT_PLAN wave A)
  performUi: MappingGroup[];
  performDefaults: Record<string, unknown>;
  sample: { name: string; root: number }; // loaded sampler file (name "" = synth bell)
  startBar: number; // jump-to-bar: where play begins
  automation: AutomationTrack; // drawable affect curve (the demo ARCs)
  presets: string[]; // saved session names (fetched over REST)
  roll: RollBar[]; // rolling window of recent bars' events (piano-roll)
  lint: Lint; // live theory-lint status of the current bar
  phraseBars: number;
  bar: number | null;
  trace: string[];
  schema: SchemaMsg | null;
  error: string | null;
}

const DEFAULT_AUTOMATION: AutomationTrack = { enabled: false, loop_bars: 0, points: [] };

export const mainStore = createStore<MainState>({
  connected: false,
  running: false,
  seed: 42,
  snapshotAffect: DEFAULT_AFFECT,
  engineAffect: DEFAULT_AFFECT,
  context: null,
  params: null,
  mapped: {},
  pinned: {},
  paramUi: [],
  paramDefaults: {},
  mapping: {},
  mappingUi: [],
  mappingDefaults: {},
  slots: [],
  console: {},
  consoleUi: [],
  consoleDefaults: {},
  dramaturg: {},
  dramaturgUi: [],
  dramaturgDefaults: {},
  perform: {},
  performUi: [],
  performDefaults: {},
  sample: { name: "", root: 72 },
  startBar: 0,
  automation: DEFAULT_AUTOMATION,
  presets: [],
  roll: [],
  lint: { clean: true, violations: [] },
  phraseBars: 8,
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
