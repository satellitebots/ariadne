import { useEffect, useState } from "react";
import { ago, call, duration, LIVE, SAY, type Progress, type Run } from "../api";
import type { Selection } from "../App";

const ASKS: Record<string, string> = { commands: "run", paths: "write", tools: "use" };
const WORK = new Set(["tool", "job", "looping", "quiet"]);   // what a worker does, pushed as it happens

// The thread: one line through the run's steps, drawn as far as the run has got.
export default function RunView({ id, tick, go }: { id: string; tick: number; go: (s: Selection) => void }) {
  const [r, setR] = useState<Run | null>(null);
  const [p, setP] = useState<Progress | null>(null);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [job, setJob] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  useEffect(() => {
    call<Run>("run_show", { run: id }).then(setR).catch((e) => setErr(e.message));
    call<Progress>("progress", { run: id, recent: 0 }).then(setP).catch(() => {});
  }, [id, tick]);

  async function act(verb: string, args: Record<string, unknown> = {}) {
    setErr(""); setConfirmCancel(false);
    try {
      const out = await call<{ id: string }>(verb, { run: id, ...args });
      if (verb === "rerun") go({ kind: "run", id: out.id });
      setR(await call<Run>("run_show", { run: id }));
    } catch (e) { setErr((e as Error).message); }
  }

  if (!r) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;
  const live = LIVE.has(r.status);
  const elapsed = (r.ended || Date.now() / 1000) - (r.started || r.created);
  const warn = p && (p.looping_note || p.quiet_note);

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
          {r.status === "running" && <button onClick={() => act("park_run")} title="It stops at its next tool call and gives the machine back">Park</button>}
          {r.status === "parked" && <button className="primary" onClick={() => act("resume")}>Resume</button>}
          {live && !confirmCancel && <button className="quiet" onClick={() => setConfirmCancel(true)}>Cancel</button>}
          {live && confirmCancel && <>
            <button className="danger-btn" onClick={() => act("cancel")}>Cancel the run</button>
            <button className="quiet" onClick={() => setConfirmCancel(false)}>Keep it</button>
          </>}
          {!live && <button className="primary" onClick={() => act("rerun")}>Run again</button>}
        </div>
      </header>
      {err && <p className="banner error" role="alert">{err}</p>}
      {r.ask && (
        <div className="banner ask" role="alert">
          <p>Step {r.step} wants to {ASKS[r.ask.kind] ?? "use"} <code className="what">{r.ask.what}</code>. It waits for your answer; the machine is free meanwhile.</p>
          <p className="dim small">It matches the ask rule <code>{r.ask.rule}</code> in permissions.yaml (the Rules page).</p>
          <div className="row">
            <button className="primary" onClick={() => act("approve")}>Approve for this run</button>
            <button onClick={() => { act("reject", { why: note }); setNote(""); }}>Reject{note.trim() ? " with the note below" : ""}</button>
          </div>
        </div>
      )}
      {r.error && !live && <p className={`banner ${r.status === "done" ? "" : "warn"}`}>{r.error}</p>}
      {live && warn && <p className="banner warn" role="status">{p!.looping_note || p!.quiet_note}</p>}

      {p && (p.tool_calls > 0 || p.model_calls > 0) && (
        <dl className="stats progress" aria-label="What it has done">
          <div><dt>Last activity</dt><dd>{p.seconds_since_activity != null ? (p.seconds_since_activity < 60 ? `${p.seconds_since_activity} s ago` : ago(Date.now() / 1000 - p.seconds_since_activity)) : "–"}</dd></div>
          <div><dt>Tool calls</dt><dd>{p.tool_calls}</dd></div>
          <div><dt>Model calls</dt><dd>{p.model_calls}</dd></div>
          <div className="wide"><dt>Files changed</dt><dd className="files">{p.files_changed.length ? p.files_changed.map((f) => <code key={f}>{f}</code>) : <span className="dim">none yet</span>}</dd></div>
        </dl>
      )}

      {live && (
        <form className="steer" onSubmit={(e) => { e.preventDefault(); if (note.trim()) { act("steer", { text: note }); setNote(""); } }}>
          <label htmlFor="steer">Steer this run</label>
          <div className="row">
            <input id="steer" value={note} onChange={(e) => setNote(e.target.value)}
                   placeholder={r.status === "parked" ? "What should change? It is read before the run continues." : "A note for this run"} />
            <button type="submit" disabled={!note.trim()}>Send note</button>
          </div>
          <p className="dim small">A note holds for every later step of this run.{r.status === "running" ? " To change course now: park it, talk it over with the orchestrator, send a note, then resume." : ""}</p>
        </form>
      )}
      {r.notes.length > 0 && (
        <section className="notes" aria-labelledby="notes-h">
          <h2 id="notes-h">Notes it follows</h2>
          <ul className="plain small">{r.notes.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </section>
      )}

      <ol className={`thread ${r.status}`}>
        {r.steps.map((s) => {
          const last = s.attempts[s.attempts.length - 1];
          const raw = last ? last.status : r.status === "running" && r.step === s.n ? "running" : "pending";
          const here = live && r.step === s.n;
          const state = !live && raw === "running" ? "stopped" : here && ["asking", "parked"].includes(r.status) ? r.status : raw;
          const work = here ? r.events.filter((e) => WORK.has(e.kind) && e.detail.startsWith(`step ${s.n}`)).slice(-5) : [];
          return (
            <li key={s.n} className={`knot ${state} ${here ? "here" : ""}`}>
              <button className="knot-head" onClick={() => setOpen(open === s.n ? null : s.n)} aria-expanded={open === s.n}>
                <span className="n">{s.n}</span>
                <span className="title">{s.title}</span>
                <span className="dim">{s.model}{s.attempts.length > 1 ? ` · ${s.attempts.length} attempts` : ""}</span>
                <span className={`pill ${state}`}>{state}</span>
              </button>
              {work.length > 0 && (
                <ul className="work" aria-label={`What step ${s.n} is doing`} aria-live="polite">
                  {work.map((e, i) => (
                    <li key={i} className={e.kind}>{e.detail.replace(/^step \d+( check)?: /, "")} <span className="dim">{ago(e.ts)}</span></li>
                  ))}
                </ul>
              )}
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

      {r.jobs.length > 0 && (
        <section aria-labelledby="rjobs-h">
          <h2 id="rjobs-h">Jobs</h2>
          <ul className="jobs">
            {r.jobs.map((j) => (
              <li key={j.id}>
                <button className="job-head" aria-expanded={job === j.id} onClick={() => setJob(job === j.id ? null : j.id)}>
                  <span className={`pill ${j.status === "done" ? "done" : j.status === "running" ? "running" : j.status === "failed" ? "failed" : ""}`}>{j.status}</span>
                  <span className="job-why">{j.why || j.command}</span>
                  <span className="dim small">{j.seconds != null ? duration(j.seconds) : ""}</span>
                </button>
                {job === j.id && (
                  <div className="job-body">
                    <pre className="cmd">{j.command}</pre>
                    {j.log_tail && <pre className="logtail">{j.log_tail}</pre>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {r.result && !live && (
        <section aria-labelledby="res-h">
          <h2 id="res-h">Result</h2>
          <pre className="report">{r.result.slice(0, 4000)}</pre>
        </section>
      )}

      <section>
        <button className="link" onClick={() => setShowLog(!showLog)} aria-expanded={showLog}>
          {showLog ? "Hide the activity" : `Show the activity (${r.events.length})`}
        </button>
        {showLog && (
          <ol className="log">
            {r.events.map((e, i) => (
              <li key={i} className={e.kind}><time>{new Date(e.ts * 1000).toLocaleTimeString()}</time><b>{e.kind}</b><span>{e.detail}</span></li>
            ))}
          </ol>
        )}
        <p className="dim small">Files are in <span className="path">{r.workspace}</span></p>
      </section>
    </article>
  );
}
