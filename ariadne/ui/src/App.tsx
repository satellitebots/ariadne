import { useCallback, useEffect, useRef, useState } from "react";
import { call, stream, type Draft, type Machine, type RunSummary, type Task } from "./api";
import MachineBar from "./parts/MachineBar";
import Sidebar from "./parts/Sidebar";
import Home from "./parts/Home";
import TaskView from "./parts/TaskView";
import RunView from "./parts/RunView";
import DraftView from "./parts/DraftView";
import Orchestrator from "./parts/Orchestrator";
import RunsPage from "./parts/RunsPage";
import MachinePage from "./parts/MachinePage";
import TemplatesPage from "./parts/TemplatesPage";
import RulesPage from "./parts/RulesPage";

export type Page = "home" | "runs" | "machine" | "templates" | "rules";
export type Selection =
  | { kind: Page }
  | { kind: "task"; id: string }
  | { kind: "run"; id: string }
  | { kind: "draft"; id: string };

const PAGES = new Set(["runs", "machine", "templates", "rules"]);

function fromHash(): Selection {
  const [kind, id] = location.hash.slice(1).split("/");
  if ((kind === "task" || kind === "run" || kind === "draft") && id) return { kind, id };
  if (PAGES.has(kind)) return { kind: kind as Page };
  return { kind: "home" };
}

export default function App() {
  const [sel, setSel] = useState<Selection>(fromHash);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [recent, setRecent] = useState<RunSummary[]>([]);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [tick, setTick] = useState(0);              // bumps when the store changes; views refetch on it
  const [error, setError] = useState("");
  const pending = useRef<number | null>(null);

  const go = useCallback((s: Selection) => {
    setSel(s);
    location.hash = s.kind === "home" ? "" : "id" in s ? `${s.kind}/${s.id}` : s.kind;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [t, d, r] = await Promise.all([
        call<Task[]>("tasks"), call<Draft[]>("drafts"), call<RunSummary[]>("runs", { limit: 60 }),
      ]);
      setTasks(t); setDrafts(d); setRecent(r); setError("");
    } catch (e) {
      setError(`Ariadne is not answering: ${(e as Error).message}. Is \`ariadne ui\` still running?`);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onHash = () => setSel(fromHash());
    window.addEventListener("hashchange", onHash);
    const stop = stream(
      () => {   // coalesce bursts of events into one refresh
        if (pending.current) window.clearTimeout(pending.current);
        pending.current = window.setTimeout(() => { refresh(); setTick((t) => t + 1); }, 300);
      },
      setMachine,
    );
    return () => { stop(); window.removeEventListener("hashchange", onHash); };
  }, [refresh]);

  const live = recent.filter((r) => ["queued", "waiting", "running", "parked", "asking"].includes(r.status));
  const draftId = sel.kind === "draft" ? sel.id : "";

  return (
    <div className="shell">
      <a className="skip" href="#main-content">Skip to the page</a>
      <MachineBar machine={machine} live={live} go={go} />
      <Sidebar tasks={tasks} drafts={drafts} recent={recent} sel={sel} go={go} />
      <main className="main" id="main-content" tabIndex={-1}>
        {error && <p className="banner error" role="alert">{error}</p>}
        {sel.kind === "home" && <Home tasks={tasks} recent={recent} drafts={drafts} go={go} />}
        {sel.kind === "runs" && <RunsPage recent={recent} tick={tick} go={go} />}
        {sel.kind === "machine" && <MachinePage machine={machine} tick={tick} />}
        {sel.kind === "templates" && <TemplatesPage go={go} />}
        {sel.kind === "rules" && <RulesPage />}
        {sel.kind === "task" && <TaskView id={sel.id} tick={tick} go={go} />}
        {sel.kind === "run" && <RunView id={sel.id} tick={tick} go={go} />}
        {sel.kind === "draft" && <DraftView id={sel.id} tick={tick} go={go} />}
      </main>
      <Orchestrator draftId={draftId} go={go} tick={tick} />
    </div>
  );
}
