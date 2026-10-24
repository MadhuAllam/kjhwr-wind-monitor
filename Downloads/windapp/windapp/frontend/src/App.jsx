import React, { useState } from "react";
import { useApi } from "./api.js";
import { DecisionView, AccuracyView } from "./views.jsx";

export default function App() {
  const [tab, setTab] = useState("decision");
  const [cutoff, setCutoff] = useState("09:00");
  const [retry, setRetry] = useState(0);
  const cfg = useApi("/api/config", retry);

  return (
    <>
      <header>
        <div>
          <h1>Day-Ahead Wind Forecast Desk</h1>
          <small>GB national wind · Elexon WINDFOR vs FUELHH · delivery days in January 2026</small>
        </div>
        <nav>
          <button className={tab === "decision" ? "on" : ""} onClick={() => setTab("decision")}>Decision view</button>
          <button className={tab === "accuracy" ? "on" : ""} onClick={() => setTab("accuracy")}>Forecast accuracy</button>
        </nav>
        <label className="hdr-label">
          Gate-closure cutoff on D-1 (London)
          <input type="time" value={cutoff} onChange={(e) => e.target.value && setCutoff(e.target.value)} />
        </label>
      </header>
      <main>
        {cfg.loading && <p>Connecting to the API…</p>}
        {cfg.error && (
          <div className="banner warn">
            <b>Could not load configuration.</b> {cfg.error}{" "}
            <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
          </div>
        )}
        {cfg.data && (tab === "decision"
          ? <DecisionView cfg={cfg.data} cutoff={cutoff} />
          : <AccuracyView cutoff={cutoff} />)}
      </main>
    </>
  );
}
