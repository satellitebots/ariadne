import { useEffect, useState } from "react";
import { call, when, type Draft, type Flow, type RunSummary, type Task } from "../api";
import type { Selection } from "../App";

type Props = { tasks: Task[]; live: RunSummary[]; drafts: Draft[]; go: (s: Selection) => void };

// Where a new task starts: say what you want, pick the template it fits. The orchestrator fills in the rest with you.
export default function Home({ tasks, live, go }: Props) {
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

  const upcoming = tasks.filter((t) => t.scheduled && t.next_due).sort((a, b) => (a.next_due! - b.next_due!)).slice(0, 4);

  return (
    <div className="home">
      <section className="start">
        <h1>What should run on this machine?</h1>
        <p className="lead">Describe the work. The orchestrator turns it into a task you can read, sign, run now or put on a schedule.</p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3}
                  placeholder="Every weekday at 7, check how GOOGL moved and what the indicators say"
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
          {err && <span className="error">{err}</span>}
        </div>
      </section>

      {(live.length > 0 || upcoming.length > 0) && (
        <section className="glance">
          {live.length > 0 && (
            <div>
              <h2>Running now</h2>
              <ul className="plain">
                {live.map((r) => (
                  <li key={r.id}><a href={`#run/${r.id}`}>{r.task}</a> <span className={`pill ${r.status}`}>{r.status}</span>
                    <span className="dim"> step {r.step} of {r.steps_total}</span></li>
                ))}
              </ul>
            </div>
          )}
          {upcoming.length > 0 && (
            <div>
              <h2>Coming up</h2>
              <ul className="plain">
                {upcoming.map((t) => (
                  <li key={t.id}><a href={`#task/${t.id}`}>{t.name}</a> <span className="dim">{when(t.next_due)}</span></li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
