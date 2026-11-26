import { useEffect, useState } from "react";
import { call, type Draft, type Flow } from "../api";
import type { Selection } from "../App";

// The flows a task can start from: what each is for, what it asks, its steps and the tools a step may use.
export default function TemplatesPage({ go }: { go: (s: Selection) => void }) {
  const [flows, setFlows] = useState<Flow[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => { call<Flow[]>("flows").then(setFlows).catch((e) => setErr(e.message)); }, []);

  async function start(flow: string) {
    setErr("");
    try { const d = await call<Draft>("draft", { flow }); go({ kind: "draft", id: d.id }); }
    catch (e) { setErr((e as Error).message); }
  }

  return (
    <article className="templates">
      <header className="head"><div><h1>Templates</h1>
        <p className="lead">A task starts from one of these. The orchestrator asks its questions, you sign the result.</p></div></header>
      {err && <p className="banner error" role="alert">{err}</p>}
      <ul className="tpl-list">
        {flows.map((f) => (
          <li key={f.name} className="tpl">
            <div className="tpl-head">
              <div><h2>{f.name}</h2><p>{f.description}</p></div>
              <button onClick={() => start(f.name)}>Start a draft</button>
            </div>
            {f.when && <p className="dim small">Use it for: {f.when}</p>}
            <div className="tpl-cols">
              <div>
                <h3>It asks</h3>
                {Object.keys(f.params).length === 0 ? <p className="dim small">Nothing: you describe the work.</p> : (
                  <ul className="plain small">{Object.entries(f.params).map(([k, q]) => <li key={k}>{q}</li>)}</ul>
                )}
              </div>
              <div>
                <h3>Steps</h3>
                {f.steps.length === 0 ? <p className="dim small">Planned with you for each task.</p> : (
                  <ol className="small steps-list">{f.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
                )}
              </div>
              <div>
                <h3>Tools</h3>
                <p className="small tool-tags">{f.tools.map((t) => <code key={t}>{t}</code>)}</p>
                <p className="dim small">Runs on {f.model}</p>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </article>
  );
}
