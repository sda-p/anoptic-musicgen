import { useMain } from "./store";
import { AffectPad } from "./components/AffectPad";
import { TensionFader } from "./components/TensionFader";
import { TelemetryHeader } from "./components/TelemetryHeader";
import { TraceLog } from "./components/TraceLog";
import { Meter } from "./components/Meter";
import { Transport } from "./components/Transport";
import { BottomPanel } from "./components/BottomPanel";

export default function App() {
  const s = useMain();
  return (
    <div className="app">
      <header className="topbar">
        <h1>anoptic · playground</h1>
        <div className="badges">
          <span className={`badge ${s.connected ? "badge-ok" : "badge-off"}`}>
            {s.connected ? "connected" : "offline"}
          </span>
          <span className={`badge ${s.running ? "badge-live" : "badge-idle"}`}>
            {s.running ? "live" : "idle"}
          </span>
        </div>
        <div className="spacer" />
        <Transport />
      </header>

      <main className="grid">
        <section className="panel">
          <div className="panel-title">affect</div>
          <AffectPad />
          <TensionFader />
        </section>

        <section className="panel">
          <div className="panel-title">now playing</div>
          <TelemetryHeader />
          <Meter />
        </section>

        <section className="panel trace-panel">
          <div className="panel-title">decision trace</div>
          <TraceLog />
        </section>
      </main>

      <BottomPanel />

      {s.error && <div className="error-bar">error: {s.error}</div>}
    </div>
  );
}
