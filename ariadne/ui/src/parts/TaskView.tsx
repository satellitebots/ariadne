import { useEffect, useState } from "react";
import { ago, beads, call, duration, SAY, when, type Draft, type TaskDetail } from "../api";
import type { Selection } from "../App";

const PRESETS: [string, string][] = [
  ["Only when I start it", "manual"],
  ["Weekdays at 7:00", "0 7 * * 1-5"],
  ["Every day at 7:00", "0 7 * * *"],
  ["Every Monday at 8:00", "0 8 * * 1"],
];

function fill(text: string, params?: Record<string, string>): string {
  return text.replace(/\{(\w+)\}/g, (m, k) => (params?.[k] ? params[k] : k === "checks" ? "checks" : m));
}

export default function TaskView({ id, tick, go }: { id: string; tick: number; go: (s: Selection) => void }) {
  const [t, setT] = useState<TaskDetail | null>(null);
  const [err, setErr] = useState("");
  const [showDef, setShowDef] = useState(false);
  const [custom, setCustom] = useState("");
  const [confirmRetire, setConfirmRetire] = useState(false);

  useEffect(() => { call<TaskDetail>("task", { task: id }).then(setT).catch((e) => setErr(e.message)); }, [id, tick]);

  async function act<T>(verb: string, args: Record<string, unknown>, then?: (x: T) => void) {
    setErr("");
    try { const out = await call<T>(verb, args); then?.(out); setT(await call<TaskDetail>("task", { task: id })); }
    catch (e) { setErr((e as Error).message); }
  }

  if (!t) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;
  const retired = t.status === "retired";
  const s = t.stats;
  const steps = t.spec?.steps ?? [];

  return (
    <article className="task">
      <header className="head">
        <div>
          <p className="crumb">Task · {t.flow} · version {t.version}{retired ? " · retired" : ""}</p>
          <h1>{t.name}</h1>
          <p className="lead">{t.goal}</p>
          <p className="facts">
            <span>{t.trigger}</span>
            {t.scheduled && t.next_due ? <span>next run {when(t.next_due)}</span> : null}
            {t.spec?.workspace ? <span className="path">{t.spec.workspace}</span> : null}
          </p>
        </div>
        {!retired && (
          <div className="actions">
            <button className="primary" onClick={() => act<{ id: string }>("run", { task: t.id }, (r) => go({ kind: "run", id: r.id }))}>Run now</button>
            <button onClick={() => act<Draft>("edit", { task: t.id }, (d) => go({ kind: "draft", id: d.id }))}>Edit</button>
          </div>
        )}
      </header>
      {err && <p className="banner error" role="alert">{err}</p>}

      {s && s.runs > 0 && (
        <dl className="stats" aria-label="How its runs went">
          <div><dt>Runs</dt><dd>{s.runs}</dd></div>
          <div><dt>Done</dt><dd className="ok">{s.done}</dd></div>
          <div><dt>Needed you</dt><dd className={s.needs_you ? "warn" : ""}>{s.needs_you}</dd></div>
          <div><dt>Failed</dt><dd className={s.failed ? "bad" : ""}>{s.failed}</dd></div>
          <div><dt>Typical run</dt><dd>{s.typical_s ? duration(s.typical_s) : "–"}</dd></div>
        </dl>
      )}

      {!retired && (
        <section aria-labelledby="when-h">
          <h2 id="when-h">When it runs</h2>
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
      )}

      <section aria-labelledby="runs-h">
        <h2 id="runs-h">Runs</h2>
        {t.runs.length === 0 && <p className="dim">No runs yet. Run it now, or give it a schedule.</p>}
        <ol className="runs">
          {t.runs.map((r) => (
            <li key={r.id}>
              <a href={`#run/${r.id}`}>
                <span className={`pill ${r.status}`}>{SAY[r.status] ?? r.status}</span>
                <span>{ago(r.created)}</span>
                <span className="dim">v{r.version} · {r.trigger}</span>
                <span className="beads" aria-label={`step ${r.step} of ${r.steps_total}`}>{beads(r).map((b, i) => <i key={i} className={b} />)}</span>
              </a>
            </li>
          ))}
        </ol>
      </section>

      {steps.length > 0 && (
        <section aria-labelledby="steps-h">
          <h2 id="steps-h">What it does</h2>
          <ol className="thread plan">
            {steps.map((st, i) => (
              <li key={i} className="knot pending">
                <div className="knot-head static">
                  <span className="n">{i + 1}</span>
                  <span className="title">{st.title}</span>
                  {st.each && <span className="each" title="This step is repeated, once per line of the Steps list an earlier step writes">once per step in {st.each}</span>}
                  <span className="dim small">{(st.outputs || []).map((o) => fill(o, t.spec.params)).join(", ")}</span>
                </div>
                <div className="knot-body">
                  <p className="small">{fill(st.instruction, t.spec.params)}</p>
                  {st.gate ? <p className="dim small">Checked by {st.gate.type === "run" ? "a script" : "a reviewer"}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <button className="link" onClick={() => setShowDef(!showDef)} aria-expanded={showDef}>
          {showDef ? "Hide the definition" : "Show the definition"}
        </button>
        {showDef && <pre className="yaml">{t.yaml}</pre>}
      </section>

      {!retired && (
        <section className="danger">
          {!confirmRetire ? (
            <button className="quiet" onClick={() => setConfirmRetire(true)}>Retire this task</button>
          ) : (
            <div className="row">
              <span>Retire {t.name}? It stops running; its history stays.</span>
              <button className="primary" onClick={() => act("retire", { task: t.id }, () => setConfirmRetire(false))}>Retire</button>
              <button className="quiet" onClick={() => setConfirmRetire(false)}>Keep it</button>
            </div>
          )}
        </section>
      )}
    </article>
  );
}
