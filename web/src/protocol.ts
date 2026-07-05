// TypeScript mirror of the server's WebSocket/JSON messages (musicgen/
// playground/telemetry.py). The single source of truth for field NAMES is the
// /api/schema payload; these types just give the fixed message envelopes shape.

export interface Affect {
  valence: number;
  energy: number;
  tension: number;
}

export interface BarContext {
  bar: number;
  scale: string;
  chord_sym: string;
  chord_pcs: number[];
  next_chord_sym: string;
  tension: number;
  cadence_slot: string;
  cadence_policy: string;
  modulation: string;
}

export interface Params {
  tempo_bpm: number;
  note_density: number;
  roughness: number;
  articulation: number;
  velocity_center: number;
  accent_depth: number;
  register_center: number;
  layers: string[];
  harmonic_rhythm: number;
  dissonance_budget: number;
  cadence_policy: string;
  instruments: [string, string][];
  filter_cutoff: number;
  reverb_send: number;
  delay_send: number;
  drive: number;
  stereo_width: number;
}

export interface FieldDef {
  name: string;
  default: unknown;
  kind: "scalar" | "struct";
}

export interface EnumOption {
  label: string;
  value: string | number;
}

export interface ParamSpec {
  name: string;
  kind: "float" | "int" | "enum";
  boundary: string; // "beat" | "bar" | "phrase"
  min?: number;
  max?: number;
  step?: number;
  options?: EnumOption[];
}

export interface ParamGroup {
  group: string;
  label: string;
  params: ParamSpec[];
}

export interface MappingFieldSpec {
  name: string;
  default: number | number[];
  kind: "scalar" | "range";
  step: number;
}

export interface MappingGroup {
  group: string;
  fields: MappingFieldSpec[];
}

export interface EventDef {
  start: number;
  dur: number;
  pitch: number;
  velocity: number;
  layer: string;
  degree: number | null;
  chord: string;
  role: string;
}

export interface Lint {
  clean: boolean;
  violations: { rule: string; message: string }[];
}

export interface SchemaMsg {
  type: "schema";
  affect: Record<"valence" | "energy" | "tension", { min: number; max: number; default: number }>;
  overridable: string[];
  params: FieldDef[];
  mapping: FieldDef[];
  mapping_ui: MappingGroup[];
  dramaturg_ui: MappingGroup[];
  console: FieldDef[];
  console_ui: MappingGroup[];
  instrument_tiers: [string, [string, number][]][];
  layer_gates: [string, number][];
  layers: string[];
  layers_boundary: string;
  param_ui: ParamGroup[];
  patches_by_layer: Record<string, string[]>;
  modes: { name: string; brightness: number }[];
  meter: { numerator: number; denominator: number };
  phrase_bars: number;
}

export interface AutomationPoint {
  bar: number;
  valence: number;
  energy: number;
  tension: number;
}

export interface AutomationTrack {
  enabled: boolean;
  loop_bars: number;
  points: AutomationPoint[];
}

export interface SnapshotMsg {
  type: "snapshot";
  running: boolean;
  seed: number;
  affect: Affect;
  pinned: Record<string, unknown>;
  mapping: Record<string, unknown>;
  slots: string[];
  console: Record<string, number>;
  sample: { name: string; root: number };
  start_bar: number;
  automation: AutomationTrack;
  dramaturg: Record<string, number | boolean>;
}

export interface BarMsg {
  type: "bar";
  bar: number;
  context: BarContext;
  params: Params;
  mapped: Record<string, number | string>;
  affect: Affect;
  tempo_points: [number, number][];
  trace: string[];
  events: EventDef[];
  raw_events: EventDef[];
  lint: Lint;
  pinned: string[];
}

export interface MeterMsg {
  type: "meter";
  level: number;
  cpu: number;
  bars: number;
}

export interface ErrorMsg {
  type: "error";
  error: string;
  for?: string | null;
}

export type ServerMessage = SchemaMsg | SnapshotMsg | BarMsg | MeterMsg | ErrorMsg;
