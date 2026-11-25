import { useEffect, useState } from "react";
import { ago, call, when, type Draft, type TaskDetail } from "../api";
import type { Selection } from "../App";

const PRESETS: [string, string][] = [
  ["Only when I start it", "manual"],
  ["Weekdays at 7:00", "0 7 * * 1-5"],
  ["Every day at 7:00", "0 7 * * *"],
  ["Every Monday at 8:00", "0 8 * * 1"],
];

export default function TaskView({ id, tick, go }: { id: string; tick: number; go: (s: Selection) => void }) {
  const [t, setT] = useState<TaskDetail | null>(null);
  const [err, setErr] = useState("");
  const [showDef, setShowDef] = useState(false);
  const [custom, setCustom] = useState("");

  useEffect(() => { call<TaskDetail>("task", { task: id }).then(setT).catch((e) => setErr(e.message)); }, [id, tick]);

  async function act<T>(verb: string, args: Record<string, unknown>, then?: (x: T) => void) {
    setErr("");
    try { const out = await call<T>(verb, args); then?.(out); setT(await call<TaskDetail>("task", { task: id })); }
    catch (e) { setErr((e as Error).message); }
  }

  if (!t) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;

  return (
    <article className="task">
      <header className="head">
        <div>
          <h1>{t.name}</h1>
          <p className="lead">{t.goal}</p>
          <p className="facts">
            <span>{t.flow}</span><span>version {t.version}</span><span>{t.trigger}</span>
            {t.scheduled && t.next_due ? <span>next run {when(t.next_due)}</span> : null}
          </p>
        </div>
        <div className="actions">
          <button className="primary" onClick={() => act<{ id: string }>("run", { task: t.id }, (r) => go({ kind: "run", id: r.id }))}>Run now</button>
          <button onClick={() => act<Draft>("edit", { task: t.id }, (d) => go({ kind: "draft", id: d.id }))}>Edit</button>
        </div>
      </header>
      {err && <p className="banner error">{err}</p>}

      <section>
        <h2>When it runs</h2>
        <div className="presets">
          {PRESETS.map(([label, trig]) => (
            <button key={trig} className={t.trigger.includes(trig) || (trig === "manual" && t.trigger.startsWith("runs when")) ? "chip on" : "chip"}
                    onClick={() => act("schedule", { task: t.id, trigger: trig })}>{label}</button>
          ))}
          <form onSubmit={(e) => { e.preventDefault(); if (custom.trim()) act("schedule", { task: t.id, trigger: custom.trim() }); }}>
            <input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="cron, or 2026-12-01T07:00" aria-label="Custom schedule" />
          </form>
          {t.scheduled && t.next_due ? <button className="quiet" onClick={() => act("unschedule", { task: t.id })}>Pause schedule</button> : null}
        </div>
        <p className="dim small">Changing the schedule signs a new version; runs in progress finish on the version they started.</p>
      </section>

      <section>
        <h2>Runs</h2>
        {t.runs.length === 0 && <p className="dim">No runs yet. Run it now, or give it a schedule.</p>}
        <ol className="runs">
          {t.runs.map((r) => (
            <li key={r.id}>
              <a href={`#run/${r.id}`}>
                <span className={`pill ${r.status}`}>{r.status}</span>
                <span>{ago(r.created)}</span>
                <span className="dim">v{r.version} · {r.trigger}</span>
                <span className="steps" aria-label={`step ${r.step} of ${r.steps_total}`}>
                  {Array.from({ length: r.steps_total }, (_, i) => (
                    <i key={i} className={i < r.step - (r.status === "done" ? 0 : 1) ? "done" : i === r.step - 1 ? r.status : ""} />
                  ))}
                </span>
              </a>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <button className="link" onClick={() => setShowDef(!showDef)} aria-expanded={showDef}>
          {showDef ? "Hide the definition" : "Show the definition"}
        </button>
        {showDef && <pre className="yaml">{t.yaml}</pre>}
      </section>
    </article>
  );
}
