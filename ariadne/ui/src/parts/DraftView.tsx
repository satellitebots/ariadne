import { useEffect, useState } from "react";
import { call, type Draft, type Task } from "../api";
import type { Selection } from "../App";

// A placeholder with no value yet stays visible as "(question)", so the gap shows.
function fill(text: string, params?: Record<string, string>): string {
  return text.replace(/\{(\w+)\}/g, (_, k) => (params?.[k] ? params[k] : `(${k})`));
}

// A draft is the definition while you and the orchestrator shape it. You can also edit the YAML yourself.
export default function DraftView({ id, tick, go }: { id: string; tick: number; go: (s: Selection) => void }) {
  const [d, setD] = useState<Draft | null>(null);
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    call<Draft>("draft_show", { draft: id }).then((x) => { setD(x); if (!dirty) setText(x.yaml); }).catch((e) => setErr(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, tick]);

  async function save() {
    setBusy(true); setErr("");
    try { const x = await call<Draft>("draft_update", { draft: id, yaml: text }); setD(x); setText(x.yaml); setDirty(false); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  async function sign() {
    setBusy(true); setErr("");
    try {
      if (dirty) await call<Draft>("draft_update", { draft: id, yaml: text });
      const t = await call<Task & { run?: string }>("sign", { draft: id });
      go(t.run ? { kind: "run", id: t.run } : { kind: "task", id: t.id });
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  if (!d) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;
  const s = d.spec;

  return (
    <article className="draft">
      <header className="head">
        <div>
          <p className="crumb">Draft · {d.flow}{d.task_id ? ` · editing version ${d.base_version}` : ""}</p>
          <h1>{s.name || "Untitled task"}</h1>
          <p className="lead">{s.goal ? fill(s.goal, s.params) : "Talk it through with the orchestrator on the right, or fill in the definition below."}</p>
        </div>
        <div className="actions">
          <button className="primary" disabled={busy || (!d.ready && !dirty)} onClick={sign}
                  title={d.ready ? "It becomes a task version" : "Fill in what is missing first"}>Sign</button>
          <button className="quiet" disabled={busy} onClick={async () => { await call("drop", { draft: id }); go({ kind: "home" }); }}>Discard</button>
        </div>
      </header>
      {err && <p className="banner error">{err}</p>}

      <section className={`checklist ${d.ready ? "ready" : ""}`}>
        {d.ready ? <p>Ready to sign. Read the steps below; signing is what lets it run.</p> : (
          <>
            <p>Still to fill in</p>
            <ul>{d.problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </>
        )}
      </section>

      {s.steps && s.steps.length > 0 && (
        <section>
          <h2>Steps</h2>
          <ol className="thread plan">
            {s.steps.map((st, i) => (
              <li key={i} className="knot pending">
                <div className="knot-head static">
                  <span className="n">{i + 1}</span>
                  <span className="title">{st.title}</span>
                  <span className="dim">{(st.tools || []).join(", ")}</span>
                </div>
                <div className="knot-body">
                  <p>{fill(st.instruction, s.params)}</p>
                  {st.outputs?.length ? <p className="dim small">Leaves {st.outputs.join(", ")}</p> : null}
                  {st.gate ? <p className="dim small">Checked by {st.gate.type === "run" ? "a command" : "a reviewer"}: {st.gate.text}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h2>Definition</h2>
        <textarea className="yaml" spellCheck={false} value={text} rows={Math.min(40, text.split("\n").length + 2)}
                  onChange={(e) => { setText(e.target.value); setDirty(true); }} aria-label="Task definition (YAML)" />
        <div className="row">
          <button disabled={!dirty || busy} onClick={save}>Save changes</button>
          {dirty && <span className="dim small">Unsaved edits</span>}
        </div>
      </section>
    </article>
  );
}
