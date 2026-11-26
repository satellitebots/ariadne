import { useEffect, useState } from "react";
import { call, type Rules } from "../api";

const KINDS: [string, string][] = [["tools", "Tools"], ["commands", "Commands"], ["paths", "File writes"]];

// What workers may do (everything, unless permissions.yaml says ask or deny) and what they are known to get wrong.
export default function RulesPage() {
  const [r, setR] = useState<Rules | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => { call<Rules>("rules").then(setR).catch((e) => setErr(e.message)); }, []);

  if (!r) return err ? <p className="banner error">{err}</p> : <p className="dim">Loading…</p>;
  const p = r.permissions;
  const listed = (mode: "ask" | "deny") => KINDS.flatMap(([k]) => (p[mode]?.[k] ?? []).map((v) => [k, v]));
  const asks = listed("ask"), denies = listed("deny");

  return (
    <article className="rules">
      <header className="head"><div><h1>Rules</h1>
        <p className="lead">Workers may do anything on this machine. Nothing is refused unless you list it here.</p></div></header>

      <section aria-labelledby="perm-h">
        <h2 id="perm-h">Permissions</h2>
        {p.error ? <p className="banner error">{p.error}</p> : (
          <div className="perm-grid">
            <div className="perm allow"><h3>Allowed</h3><p>Everything not listed below: any command, file, folder, site or tool.</p></div>
            <div className="perm ask"><h3>Asks you first</h3>
              {asks.length === 0 ? <p className="dim">Nothing.</p> : <ul className="plain small">{asks.map(([k, v], i) => <li key={i}><span className="dim">{k}</span> <code>{v}</code></li>)}</ul>}
              <p className="dim small">A run that reaches one waits as "asking" until you approve or reject it.</p></div>
            <div className="perm deny"><h3>Refused</h3>
              {denies.length === 0 ? <p className="dim">Nothing.</p> : <ul className="plain small">{denies.map(([k, v], i) => <li key={i}><span className="dim">{k}</span> <code>{v}</code></li>)}</ul>}</div>
          </div>
        )}
        <p className="dim small">Edit <code>{r.permissions_file}</code> to change these.</p>
      </section>

      <section aria-labelledby="rec-h">
        <h2 id="rec-h">What local workers get wrong</h2>
        <p className="dim small">From real runs (docs/WORKER-RECIPE.md). Templates, skills and checks already apply each rule; the orchestrator follows them when it defines a task.</p>
        <ol className="recipe">
          {r.recipe.map((w) => (
            <li key={w.id}>
              <span className="wid">{w.id}</span>
              <div>
                <p className="failure">{w.failure}</p>
                <p className="small"><span className="dim">Seen: </span>{w.seen.replace(/`/g, "")}</p>
                <p className="small rule-line"><span className="dim">Rule: </span>{w.rule.replace(/\*\*/g, "")}</p>
                <p className="dim small">{w.where.replace(/`/g, "")}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
