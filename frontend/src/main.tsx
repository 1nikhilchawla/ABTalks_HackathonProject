import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { theme } from "./lib/session";
import "./styles/index.css";

/** A render crash should show a recoverable screen, not a blank page. */
class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error) {
    console.error("CohortIQ crashed:", error);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div style={{ maxWidth: 520, margin: "18vh auto", padding: "0 24px", textAlign: "center" }}>
        <h1 style={{ fontSize: 18, fontWeight: 600, marginBottom: 8 }}>The interface hit an error.</h1>
        <p style={{ fontSize: 14, color: "var(--text-dim)", lineHeight: 1.6, marginBottom: 20 }}>
          Your interview is stored on the server, not in this tab — reloading resumes it exactly
          where you left off.
        </p>
        <button
          onClick={() => location.reload()}
          style={{
            background: "var(--accent)",
            color: "#fff",
            border: 0,
            borderRadius: 8,
            padding: "9px 16px",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Reload and resume
        </button>
      </div>
    );
  }
}

theme.apply();

const container = document.getElementById("root");
if (!container) throw new Error("#root missing from index.html");

createRoot(container).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
