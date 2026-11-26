import { ATTENTION, LIVE, type Draft, type RunSummary, type Task } from "../api";
import type { Page, Selection } from "../App";

type Props = { tasks: Task[]; drafts: Draft[]; recent: RunSummary[]; sel: Selection; go: (s: Selection) => void };

export default function Sidebar({ tasks, drafts, recent, sel, go }: Props) {
  // The newest run of each task says what it is doing now, or how it last ended.
  const latest = new Map<string, RunSummary>();
  for (const r of recent) if (!latest.has(r.task_id)) latest.set(r.task_id, r);
  const live = recent.filter((r) => LIVE.has(r.status));
  const attention = [...latest.values()].filter((r) => ATTENTION.has(r.status)).length;
  const is = (kind: string, id?: string) => sel.kind === kind && (!id || ("id" in sel && sel.id === id));
  const signed = tasks.filter((t) => t.status !== "retired");
  const retired = tasks.filter((t) => t.status === "retired");

  const nav: [Page, string, number | null][] = [
    ["home", "Overview", attention || null], ["runs", "Runs", live.length || null],
    ["machine", "Machine", null], ["templates", "Templates", null], ["rules", "Rules", null],
  ];

  return (
    <nav className="side" aria-label="Pages, tasks and drafts">
      <button className="new" onClick={() => go({ kind: "home" })}>New task</button>

      <ul className="nav">
        {nav.map(([page, label, count]) => (
          <li key={page}>
            <a href={page === "home" ? "#" : `#${page}`} className={is(page) ? "on" : ""} aria-current={is(page) ? "page" : undefined}>
              <span>{label}</span>
              {count ? <span className={`count ${page === "home" ? "warn" : ""}`}
                             aria-label={page === "home" ? `${count} need you` : `${count} live`}>{count}</span> : null}
            </a>
          </li>
        ))}
      </ul>

      <h2>Tasks</h2>
      {signed.length === 0 && <p className="dim small">Signed tasks appear here.</p>}
      <ul>
        {signed.map((t) => {
          const r = latest.get(t.id);
          const showRun = r && (LIVE.has(r.status) || ATTENTION.has(r.status));
          return (
            <li key={t.id}>
              <a href={`#task/${t.id}`} className={is("task", t.id) ? "on" : ""} aria-current={is("task", t.id) ? "page" : undefined}>
                <span className="name">{t.name}</span>
                <span className="sub">
                  {showRun ? <span className={`pill ${r!.status}`}>{r!.status.replace("_", " ")}{r!.status === "running" ? ` · ${r!.step}/${r!.steps_total}` : ""}</span>
                           : <span className="dim">{t.scheduled && t.next_due ? t.trigger.replace(/ \(.*\)$/, "") : "manual"}</span>}
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

      {retired.length > 0 && (
        <details className="retired">
          <summary>Retired ({retired.length})</summary>
          <ul>{retired.map((t) => <li key={t.id}><a href={`#task/${t.id}`}><span className="name dim">{t.name}</span></a></li>)}</ul>
        </details>
      )}
    </nav>
  );
}
