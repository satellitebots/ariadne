import type { Draft, RunSummary, Task } from "../api";
import type { Selection } from "../App";

type Props = { tasks: Task[]; drafts: Draft[]; live: RunSummary[]; sel: Selection; go: (s: Selection) => void };

export default function Sidebar({ tasks, drafts, live, sel, go }: Props) {
  const liveByTask = new Map(live.map((r) => [r.task_id, r]));
  const is = (kind: string, id: string) => sel.kind === kind && "id" in sel && sel.id === id;

  return (
    <nav className="side" aria-label="Tasks and drafts">
      <button className="new" onClick={() => go({ kind: "home" })}>New task</button>

      <h2>Tasks</h2>
      {tasks.length === 0 && <p className="dim small">Signed tasks appear here.</p>}
      <ul>
        {tasks.map((t) => {
          const r = liveByTask.get(t.id);
          return (
            <li key={t.id}>
              <a href={`#task/${t.id}`} className={is("task", t.id) ? "on" : ""} aria-current={is("task", t.id)}>
                <span className="name">{t.name}</span>
                <span className="sub">
                  {r ? <span className={`pill ${r.status}`}>{r.status}{r.status === "running" ? ` · step ${r.step}/${r.steps_total}` : ""}</span>
                     : <span className="dim">{t.scheduled && t.next_due ? "scheduled" : t.trigger}</span>}
                </span>
              </a>
            </li>
          );
        })}
      </ul>

      {drafts.length > 0 && (
        <>
          <h2>Drafts</h2>
          <ul>
            {drafts.map((d) => (
              <li key={d.id}>
                <a href={`#draft/${d.id}`} className={is("draft", d.id) ? "on" : ""}>
                  <span className="name">{d.spec.name || "Untitled draft"}</span>
                  <span className="sub dim">{d.ready ? "ready to sign" : `${d.problems.length} to fill in`} · {d.flow}</span>
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </nav>
  );
}
