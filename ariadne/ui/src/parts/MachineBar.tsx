import { useState } from "react";
import { call, duration, type Machine, type RunSummary } from "../api";
import type { Selection } from "../App";

const WHO: Record<string, string> = { worker: "A run", orchestrator: "The orchestrator", job: "A job" };

// The spindle: who holds the one GPU right now, and who is waiting for it. Always visible.
export default function MachineBar({ machine, live, go }: { machine: Machine | null; live: RunSummary[]; go: (s: Selection) => void }) {
  const [busy, setBusy] = useState(false);
  const h = machine?.holder;
  const running = live.find((r) => r.status === "running" || r.status === "waiting");
  const parked = live.find((r) => r.status === "parked");

  async function act(verb: "park_run" | "resume", run: string) {
    setBusy(true);
    try { await call(verb, { run }); } finally { setBusy(false); }
  }

  return (
    <header className="machine">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); go({ kind: "home" }); }}>Ariadne</a>
      <div className={`spindle ${h ? "held" : "free"}`}>
        <span className="spool" aria-hidden />
        {!machine && <span>Connecting to this machine…</span>}
        {machine && !h && <span>The machine is free.</span>}
        {h && (
          <span>
            {WHO[h.kind] ?? h.kind} holds the machine
            {h.kind === "worker" ? (
              <> — <a href={`#run/${h.ref}`}>{h.ref}</a></>
            ) : null}
            <span className="dim"> on {h.model || "no model"}, {duration(h.for_s)}</span>
          </span>
        )}
        {machine && machine.waiting.length > 0 && (
          <span className="queue">
            {machine.waiting.length} waiting: {machine.waiting.map((w) => (WHO[w.kind] ?? w.kind).toLowerCase()).join(", ")}
          </span>
        )}
      </div>
      <div className="machine-actions">
        {running && !parked && (
          <button className="quiet" disabled={busy} onClick={() => act("park_run", running.id)}
                  title="It stops at its next step boundary and gives the machine back">
            Park {running.task}
          </button>
        )}
        {parked && (
          <button className="primary" disabled={busy} onClick={() => act("resume", parked.id)}>
            Resume {parked.task}
          </button>
        )}
      </div>
    </header>
  );
}
