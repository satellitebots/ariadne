import { useEffect, useState } from "react";
import { ago, call, duration, type Activity, type Job, type Machine } from "../api";

const WHO: Record<string, string> = { worker: "A run", orchestrator: "The orchestrator", job: "A job" };
const LINK = (ref: string) => (ref.startsWith("r1") ? `#run/${ref}` : ref.startsWith("d") ? `#draft/${ref}` : "");

// The one machine: who holds it, who waits, the jobs it ran, and everything that happened on it lately.
export default function MachinePage({ machine, tick }: { machine: Machine | null; tick: number }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [feed, setFeed] = useState<Activity[]>([]);
  const [kinds, setKinds] = useState<"work" | "all">("work");
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    call<Job[]>("jobs", { limit: 25 }).then(setJobs).catch(() => {});
    call<Activity[]>("activity", { limit: 120 }).then(setFeed).catch(() => {});
  }, [tick]);

  const h = machine?.holder;
  const shown = kinds === "all" ? feed : feed.filter((e) => !["model", "orchestrator"].includes(e.kind));

  return (
    <article className="machine-page">
      <header className="head"><div><h1>Machine</h1><p className="lead">One GPU, one owner at a time. Everything else waits its turn, and nothing is stopped on its own.</p></div></header>

      <section className="holder-card" aria-labelledby="hold-h">
        <h2 id="hold-h">Who has it</h2>
        {!machine ? <p className="dim">Connecting…</p> : !h ? <p className="free-line">The machine is free.</p> : (
          <p className="held-line">
            <span className="spool on" aria-hidden />
            <strong>{WHO[h.kind] ?? h.kind}</strong>{" "}
            {LINK(h.ref) ? <a href={LINK(h.ref)}>{h.ref}</a> : <span>{h.ref}</span>}
            <span className="dim"> · {h.model || "no model loaded"} · {duration(h.for_s)}</span>
          </p>
        )}
        {machine && machine.waiting.length > 0 && (
          <ol className="queue-list">
            {machine.waiting.map((w, i) => (
              <li key={i}><span className="dim">{i + 1}.</span> {WHO[w.kind] ?? w.kind}{" "}
                {LINK(w.ref) ? <a href={LINK(w.ref)}>{w.ref}</a> : w.ref}
                <span className="dim"> · {w.model || "no model"} · waiting {duration(w.waited_s)}</span></li>
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="jobs-h">
        <h2 id="jobs-h">Jobs</h2>
        <p className="dim small">Heavy work (downloads, installs, builds) runs as a job with the models unloaded.</p>
        {jobs.length === 0 ? <p className="dim empty">No jobs yet.</p> : (
          <ul className="jobs">
            {jobs.map((j) => (
              <li key={j.id}>
                <button className="job-head" aria-expanded={open === j.id} onClick={() => setOpen(open === j.id ? null : j.id)}>
                  <span className={`pill ${j.status === "done" ? "done" : j.status === "running" ? "running" : j.status === "failed" ? "failed" : ""}`}>{j.status}</span>
                  <span className="job-why">{j.why || j.command}</span>
                  <span className="dim small">{j.seconds != null ? `${duration(j.seconds)} · ` : ""}{ago(j.created)}</span>
                </button>
                {open === j.id && (
                  <div className="job-body">
                    <p className="small">Run <a href={`#run/${j.run}`}>{j.run}</a>{j.exit_code != null ? ` · exit ${j.exit_code}` : ""}</p>
                    <pre className="cmd">{j.command}</pre>
                    {j.log_tail && <pre className="logtail">{j.log_tail}</pre>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="feed-h">
        <div className="section-head">
          <h2 id="feed-h">Activity</h2>
          <div className="filters small" role="tablist" aria-label="Show">
            <button role="tab" aria-selected={kinds === "work"} className={`chip ${kinds === "work" ? "on" : ""}`} onClick={() => setKinds("work")}>What changed</button>
            <button role="tab" aria-selected={kinds === "all"} className={`chip ${kinds === "all" ? "on" : ""}`} onClick={() => setKinds("all")}>Everything</button>
          </div>
        </div>
        <ol className="log feed" aria-live="polite">
          {shown.slice(0, 80).map((e, i) => (
            <li key={i} className={e.kind}>
              <time>{new Date(e.ts * 1000).toLocaleTimeString()}</time>
              <b>{e.kind}</b>
              <span>{LINK(e.ref) ? <a href={LINK(e.ref)} className="ref">{e.ref}</a> : <span className="ref dim">{e.ref}</span>} {e.detail}</span>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
