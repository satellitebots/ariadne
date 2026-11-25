import { useCallback, useEffect, useRef, useState } from "react";
import { call, stream, type Draft, type Machine, type RunSummary, type Task } from "./api";
import MachineBar from "./parts/MachineBar";
import Sidebar from "./parts/Sidebar";
import Home from "./parts/Home";
import TaskView from "./parts/TaskView";
import RunView from "./parts/RunView";
import DraftView from "./parts/DraftView";
import Orchestrator from "./parts/Orchestrator";

export type Selection =
  | { kind: "home" }
  | { kind: "task"; id: string }
  | { kind: "run"; id: string }
  | { kind: "draft"; id: string };

function fromHash(): Selection {
  const [kind, id] = location.hash.slice(1).split("/");
  if ((kind === "task" || kind === "run" || kind === "draft") && id) return { kind, id };
  return { kind: "home" };
}

export default function App() {
  const [sel, setSel] = useState<Selection>(fromHash);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [live, setLive] = useState<RunSummary[]>([]);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [tick, setTick] = useState(0);              // bumps when the store changes; views refetch on it
  const [error, setError] = useState("");
  const pending = useRef<number | null>(null);

  const go = useCallback((s: Selection) => {
    setSel(s);
    location.hash = s.kind === "home" ? "" : `${s.kind}/${s.id}`;
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [t, d, r] = await Promise.all([
        call<Task[]>("tasks"), call<Draft[]>("drafts"), call<RunSummary[]>("runs", { live: true }),
      ]);
      setTasks(t); setDrafts(d); setLive(r); setError("");
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
        pending.current = window.setTimeout(() => { refresh(); setTick((t) => t + 1); }, 250);
      },
      setMachine,
    );
    return () => { stop(); window.removeEventListener("hashchange", onHash); };
  }, [refresh]);

  const draftId = sel.kind === "draft" ? sel.id : "";

  return (
    <div className="shell">
      <MachineBar machine={machine} live={live} go={go} />
      <Sidebar tasks={tasks} drafts={drafts} live={live} sel={sel} go={go} />
      <main className="main" aria-live="polite">
        {error && <p className="banner error">{error}</p>}
        {sel.kind === "home" && <Home tasks={tasks} live={live} drafts={drafts} go={go} />}
        {sel.kind === "task" && <TaskView id={sel.id} tick={tick} go={go} />}
        {sel.kind === "run" && <RunView id={sel.id} tick={tick} go={go} />}
        {sel.kind === "draft" && <DraftView id={sel.id} tick={tick} go={go} />}
      </main>
      <Orchestrator draftId={draftId} go={go} tick={tick} />
    </div>
  );
}
