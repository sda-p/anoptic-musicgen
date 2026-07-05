import { useMain } from "../store";
import { api } from "../ws";
import type { EnumOption, ParamSpec } from "../protocol";
import { Slider } from "./Slider";

// One Tier-2 param: follow (mapper-driven, read-only) or pin (override). When
// pinned it shows the mapper's would-be value as a ghost, so an override reads
// as a departure from the heuristic.
export function ParamRow({ spec }: { spec: ParamSpec }) {
  const s = useMain();
  const name = spec.name;
  const pinned = name in s.pinned;
  const effective = s.params
    ? (s.params as unknown as Record<string, unknown>)[name]
    : s.paramDefaults[name];
  const value = pinned ? s.pinned[name] : effective;
  const ghost = s.mapped[name];

  return (
    <div className={`prow${pinned ? " is-pinned" : ""}`}>
      <div className="prow-head">
        <span className="prow-name">{name}</span>
        <span className="prow-boundary" title={`change is musical at the ${spec.boundary}`}>
          {spec.boundary}
        </span>
        <button className={`pin-btn${pinned ? " on" : ""}`}
                onClick={() => (pinned ? api.clearOverride(name) : api.setOverride(name, effective))}
                title={pinned ? "release to the mapper" : "pin this value"}>
          {pinned ? "pinned" : "auto"}
        </button>
      </div>
      <div className="prow-ctl">
        {spec.kind === "enum" ? (
          <EnumControl spec={spec} value={value} pinned={pinned}
                       onChange={(v) => api.setOverride(name, v)} />
        ) : (
          <Slider min={spec.min!} max={spec.max!} step={spec.step!}
                  value={Number(value)}
                  ghost={pinned && typeof ghost === "number" ? ghost : null}
                  disabled={!pinned}
                  onChange={(v) => api.setOverride(name, spec.kind === "int" ? Math.round(v) : v)} />
        )}
        <span className="prow-val mono">{fmtValue(value, spec)}</span>
      </div>
      {pinned && ghost !== undefined && (
        <div className="prow-ghost mono">↺ mapper {fmtValue(ghost, spec)}</div>
      )}
    </div>
  );
}

function EnumControl(props: {
  spec: ParamSpec;
  value: unknown;
  pinned: boolean;
  onChange: (v: string | number) => void;
}) {
  const options = props.spec.options ?? [];
  return (
    <select className="enum-select" disabled={!props.pinned} value={String(props.value)}
            onChange={(e) => {
              const opt = options.find((o) => String(o.value) === e.target.value);
              if (opt) props.onChange(opt.value);
            }}>
      {options.map((o: EnumOption) => (
        <option key={String(o.value)} value={String(o.value)}>{o.label}</option>
      ))}
    </select>
  );
}

function fmtValue(value: unknown, spec: ParamSpec): string {
  if (spec.kind === "enum") {
    const opt = spec.options?.find((o) => String(o.value) === String(value));
    return opt ? opt.label : String(value);
  }
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  const step = spec.step ?? 1;
  return n.toFixed(step < 0.1 ? 2 : step < 1 ? 1 : 0);
}
