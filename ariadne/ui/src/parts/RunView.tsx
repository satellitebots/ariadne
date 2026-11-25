import { useEffect, useState } from "react";
import { ago, call, duration, LIVE, type Run } from "../api";
import type { Selection } from "../App";

const SAY: Record<string, string> = {
  queued: "Queued for the machine", waiting: "Waiting for the machine", running: "Running", parked: "Parked", asking: "Asking you",
  done: "Done", failed: "Failed", timed_out: "Out of time", cancelled: "Cancelled", needs_you: "Needs you",
};

// The thread: one line through the run's steps, drawn as far as the run has got.
export default function RunView({ id, tick, go }: { id: string; tick: number; go: (s: Selection) => void }) {
  const [r, setR] = useState<Run | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [showLog, setShowLog] = useState(false);

  useEffect(() => { call<Run>("run_show", { run: id }).then(setR).catch((e) => setErr(e.message)); }, [id, tick]);

  async function act(verb: string, args: Record<string, unknown> = {}) {
    setErr("");
    try {
      const out = await call<{ id: string }>(verb, { run: id, ...args });
      if (verb === "rerun") go({ kind: "run", id: out.id });
      setR(await call<Run>("run_show", { run: id }));
    } catch (e) { setErr((e as Error).message); }
  }

  if (!r) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;
  const live = LIVE.has(r.status);
  const elapsed = (r.ended || Date.now() / 1000) - (r.started || r.created);

  return (
    <article className="run">
      <header className="head">
        <div>
          <p className="crumb"><a href={`#task/${r.task_id}`}>{r.task}</a> · version {r.version} · {r.trigger}</p>
          <h1>{SAY[r.status] ?? r.status}</h1>
          <p className="facts"><span>started {ago(r.started || r.created)}</span>{r.started ? <span>{duration(elapsed)}</span> : null}
            <span className="dim">{r.id}</span></p>
          {live && r.activity && <p className="now" aria-live="polite">Now: {r.activity.detail} <span className="dim">({ago(r.activity.ts)})</span></p>}
        </div>
        <div className="actions">
          {r.status === "running" && <button onClick={() => act("park_run")}>Park</button>}
          {r.status === "parked" && <button className="primary" onClick={() => act("resume")}>Resume</button>}
          {live && <button className="quiet" onClick={() => act("cancel")}>Cancel</button>}
          {!live && <button className="primary" onClick={() => act("rerun")}>Run again</button>}
        </div>
      </header>
      {err && <p className="banner error">{err}</p>}
      {r.ask && (
        <div className="banner ask" role="alert">
          <p>Step {r.step} {r.ask.text}. It waits for your answer; the machine is free meanwhile.</p>
          <div className="row">
            <button className="primary" onClick={() => act("approve")}>Approve for this run</button>
            <button onClick={() => { act("reject", { why: note }); setNote(""); }}>Reject{note.trim() ? " with the note below" : ""}</button>
          </div>
        </div>
      )}
      {r.error && !live && <p className={`banner ${r.status === "done" ? "" : "warn"}`}>{r.error}</p>}

      {live && (
        <form className="steer" onSubmit={(e) => { e.preventDefault(); if (note.trim()) { act("steer", { text: note }); setNote(""); } }}>
          <label htmlFor="steer">Steer this run</label>
          <div className="row">
            <input id="steer" value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder={r.status === "parked" ? "What should change? It is read before the run continues." : "A note for the next step boundary"} />
            <button type="submit" disabled={!note.trim()}>Send note</button>
          </div>
          {r.status === "running" && <p className="dim small">To change course now: park it, talk it over with the orchestrator, send a note, then resume.</p>}
        </form>
      )}

      <ol className={`thread ${r.status}`}>
        {r.steps.map((s) => {
          const last = s.attempts[s.attempts.length - 1];
          const state = last ? last.status : r.status === "running" && r.step === s.n ? "running" : "pending";
          const here = live && r.step === s.n;
          return (
            <li key={s.n} className={`knot ${state} ${here ? "here" : ""}`}>
              <button className="knot-head" onClick={() => setOpen(open === s.n ? null : s.n)} aria-expanded={open === s.n}>
                <span className="n">{s.n}</span>
                <span className="title">{s.title}</span>
                <span className="dim">{s.model}{s.attempts.length > 1 ? ` · ${s.attempts.length} attempts` : ""}</span>
                <span className={`pill ${state}`}>{state}</span>
              </button>
              {open === s.n && (
                <div className="knot-body">
                  {s.attempts.length === 0 && <p className="dim">Not started.</p>}
                  {s.attempts.map((a) => (
                    <div key={a.attempt} className="attempt">
                      <p className="dim small">Attempt {a.attempt} · {a.status}{a.ended ? ` · ${duration(a.ended - a.started)}` : ""}</p>
                      {a.gate && a.gate !== "passed" && <pre className="gate">{a.gate}</pre>}
                      {a.report && <pre className="report">{a.report}</pre>}
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <section>
        <button className="link" onClick={() => setShowLog(!showLog)} aria-expanded={showLog}>
          {showLog ? "Hide the activity" : `Show the activity (${r.events.length})`}
        </button>
        {showLog && (
          <ol className="log">
            {r.events.map((e, i) => (
              <li key={i}><time>{new Date(e.ts * 1000).toLocaleTimeString()}</time><b>{e.kind}</b><span>{e.detail}</span></li>
            ))}
          </ol>
        )}
        <p className="dim small">Files are in {r.workspace}</p>
      </section>
    </article>
  );
}
