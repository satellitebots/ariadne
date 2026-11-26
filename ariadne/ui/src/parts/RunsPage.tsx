import { useEffect, useState } from "react";
import { ago, beads, call, duration, LIVE, SAY, type RunSummary } from "../api";
import type { Selection } from "../App";

const FILTERS: [string, string, (r: RunSummary) => boolean][] = [
  ["all", "All", () => true],
  ["live", "Live", (r) => LIVE.has(r.status)],
  ["attention", "Needs you", (r) => ["asking", "needs_you", "failed", "parked"].includes(r.status)],
  ["done", "Done", (r) => r.status === "done"],
  ["stopped", "Cancelled", (r) => r.status === "cancelled"],
];

// Every run, newest first, filterable; live ones can be parked, resumed or cancelled from the row.
export default function RunsPage({ recent, tick, go }: { recent: RunSummary[]; tick: number; go: (s: Selection) => void }) {
  const [runs, setRuns] = useState<RunSummary[]>(recent);
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState("");

  useEffect(() => { call<RunSummary[]>("runs", { limit: 200 }).then(setRuns).catch((e) => setErr(e.message)); }, [tick]);

  async function act(verb: string, run: string) {
    setErr("");
    try { await call(verb, { run }); setRuns(await call<RunSummary[]>("runs", { limit: 200 })); }
    catch (e) { setErr((e as Error).message); }
  }

  const shown = runs.filter(FILTERS.find(([k]) => k === filter)![2]);
  const counts = Object.fromEntries(FILTERS.map(([k, , f]) => [k, runs.filter(f).length]));

  return (
    <article className="runs-page">
      <header className="head"><div><h1>Runs</h1><p className="lead">Every run on this machine, newest first.</p></div></header>
      {err && <p className="banner error" role="alert">{err}</p>}
      <div className="filters" role="tablist" aria-label="Filter runs">
        {FILTERS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={filter === k} className={`chip ${filter === k ? "on" : ""}`}
                  onClick={() => setFilter(k)}>{label} <span className="dim">{counts[k]}</span></button>
        ))}
      </div>
      {shown.length === 0 ? <p className="dim empty">No runs here.</p> : (
        <table className="table">
          <thead><tr><th>Task</th><th>Status</th><th>Steps</th><th>Started</th><th>Took</th><th><span className="sr">Actions</span></th></tr></thead>
          <tbody>
            {shown.map((r) => {
              const took = r.started ? (r.ended || Date.now() / 1000) - r.started : 0;
              return (
                <tr key={r.id}>
                  <td><a href={`#run/${r.id}`}>{r.task}</a><span className="dim small block">{r.trigger} · v{r.version}</span></td>
                  <td><span className={`pill ${r.status}`}>{SAY[r.status] ?? r.status}</span></td>
                  <td><span className="beads" aria-label={`step ${r.step} of ${r.steps_total}`}>{beads(r).map((b, i) => <i key={i} className={b} />)}</span></td>
                  <td className="dim">{ago(r.started || r.created)}</td>
                  <td className="dim">{took ? duration(took) : ""}</td>
                  <td className="row-actions">
                    {r.status === "running" && <button className="quiet" onClick={() => act("park_run", r.id)}>Park</button>}
                    {r.status === "parked" && <button className="primary" onClick={() => act("resume", r.id)}>Resume</button>}
                    {r.status === "asking" && <button className="primary" onClick={() => go({ kind: "run", id: r.id })}>Answer</button>}
                    {LIVE.has(r.status) && <button className="quiet" onClick={() => act("cancel", r.id)}>Cancel</button>}
                    {!LIVE.has(r.status) && <button className="quiet" onClick={() => act("rerun", r.id)}>Run again</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </article>
  );
}
