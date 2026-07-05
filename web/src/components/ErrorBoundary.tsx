import { Component, type ErrorInfo, type ReactNode } from "react";

// React error boundaries must be class components. Without one, a single
// component throw white-screens the whole playground; this degrades it to a
// legible message + reload, and logs the error to the console for debugging.
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("playground crashed:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="crash">
          <h1>the playground hit an error</h1>
          <pre className="mono">{String(this.state.error.message || this.state.error)}</pre>
          <button className="btn" onClick={() => location.reload()}>reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}
