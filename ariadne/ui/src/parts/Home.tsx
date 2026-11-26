import { useEffect, useState } from "react";
import { ago, beads, call, LIVE, SAY, when, type Draft, type Flow, type RunSummary, type Task } from "../api";
import type { Selection } from "../App";

type Props = { tasks: Task[]; recent: RunSummary[]; drafts: Draft[]; go: (s: Selection) => void };

const ASKS: Record<string, string> = { commands: "run", paths: "write", tools: "use" };

function why(r: RunSummary): string {
  if (r.ask) return `wants to ${ASKS[r.ask.kind] ?? "use"} ${r.ask.what}`;
  if (r.status === "parked") return "parked; steer it, then resume";
  return (r.error || "").split("\n").slice(-1)[0].replace(/^\[review\] /, "").slice(0, 220);
}

// Overview: what needs you, what is running, what is next, and where a new task starts.
export default function Home({ tasks, recent, drafts, go }: Props) {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [flow, setFlow] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    call<Flow[]>("flows").then((f) => { setFlows(f); setFlow((cur) => cur || f[0]?.name || ""); }).catch(() => {});
  }, []);

  async function start() {
    if (!text.trim()) return;
    setBusy(true); setErr("");
    try {
      const d = await call<Draft>("draft", { text, flow });
      go({ kind: "draft", id: d.id });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  // Each task's newest run decides whether it needs you: an old failure that has since passed does not.
  const latest = new Map<string, RunSummary>();
  for (const r of recent) if (!latest.has(r.task_id)) latest.set(r.task_id, r);
  const needs = [...latest.values()].filter((r) => ["asking", "needs_you", "failed", "parked"].includes(r.status));
  const live = recent.filter((r) => LIVE.has(r.status) && !needs.includes(r));
  const finished = recent.filter((r) => !LIVE.has(r.status)).slice(0, 5);
  const upcoming = tasks.filter((t) => t.scheduled && t.next_due).sort((a, b) => (a.next_due! - b.next_due!)).slice(0, 5);
  const ready = drafts.filter((d) => d.ready);

  return (
    <div className="home">
      {(needs.length > 0 || ready.length > 0) && (
        <section className="needs" aria-labelledby="needs-h">
          <h2 id="needs-h">Needs you</h2>
          <ul className="cards">
            {needs.map((r) => (
              <li key={r.id} className={`card ${r.status}`}>
                <a href={`#run/${r.id}`}>
                  <span className="card-top"><strong>{r.task}</strong><span className={`pill ${r.status}`}>{SAY[r.status]}</span></span>
                  <span className="card-why">{why(r) || "open the run to see why"}</span>
                  <span className="dim small">step {r.step} of {r.steps_total} · {ago(r.ended || r.started || r.created)}</span>
                </a>
              </li>
            ))}
            {ready.map((d) => (
              <li key={d.id} className="card draft">
                <a href={`#draft/${d.id}`}>
                  <span className="card-top"><strong>{d.spec.name}</strong><span className="pill">draft</span></span>
                  <span className="card-why">Ready to sign: read the steps, then sign it to let it run.</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="start" aria-labelledby="start-h">
        <h1 id="start-h">What should run on this machine?</h1>
        <p className="lead">Describe the work. The orchestrator turns it into a task you can read, sign, run now or put on a schedule.</p>
        <label className="sr" htmlFor="ask">Describe the work</label>
        <textarea id="ask" value={text} onChange={(e) => setText(e.target.value)} rows={3}
                  placeholder="Every Monday, summarise what our three main competitors shipped, with sources"
                  onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) start(); }} />
        <div className="flows" role="radiogroup" aria-label="Template">
          {flows.map((f) => (
            <label key={f.name} className={`flow ${flow === f.name ? "on" : ""}`}>
              <input type="radio" name="flow" value={f.name} checked={flow === f.name} onChange={() => setFlow(f.name)} />
              <strong>{f.name}</strong>
              <span>{f.description}</span>
            </label>
          ))}
        </div>
        <div className="row">
          <button className="primary" disabled={busy || !text.trim()} onClick={start}>Start a draft</button>
          <span className="dim small">Ctrl+Enter</span>
          {err && <span className="error">{err}</span>}
        </div>
      </section>

      <section className="glance">
        <div>
          <h2>Running now</h2>
          {live.length === 0 ? <p className="dim small">Nothing is running. The machine is yours.</p> : (
            <ul className="plain">
              {live.map((r) => (
                <li key={r.id}>
                  <a href={`#run/${r.id}`}>{r.task}</a> <span className={`pill ${r.status}`}>{SAY[r.status]}</span>
                  <span className="beads" aria-label={`step ${r.step} of ${r.steps_total}`}>{beads(r).map((b, i) => <i key={i} className={b} />)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2>Coming up</h2>
          {upcoming.length === 0 ? <p className="dim small">No schedules. Give a task one from its page.</p> : (
            <ul className="plain">
              {upcoming.map((t) => (
                <li key={t.id}><a href={`#task/${t.id}`}>{t.name}</a> <span className="dim">{when(t.next_due)}</span></li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h2>Recently finished</h2>
          {finished.length === 0 ? <p className="dim small">Finished runs appear here.</p> : (
            <ul className="plain">
              {finished.map((r) => (
                <li key={r.id}><a href={`#run/${r.id}`}>{r.task}</a> <span className={`pill ${r.status}`}>{SAY[r.status]}</span>
                  <span className="dim"> {ago(r.ended || r.created)}</span></li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
