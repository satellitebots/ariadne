// The UI is a view over the verbs (ariadne/verbs.py): every action is POST /api/v/<verb>, every change arrives on
// /api/stream. Nothing here owns a rule.

export type Gate = { type: "run" | "review"; text: string } | null;
export type Step = {
  n: number; title: string; instruction: string; model: string; tools: string[]; outputs: string[]; gate: Gate;
};
export type Spec = {
  name?: string; flow?: string; goal?: string; workspace?: string; params?: Record<string, string>;
  steps?: Step[]; gates?: Gate[]; trigger?: { kind: string; cron?: string; at?: string }; tz?: string;
  retries?: number;
};
export type Message = { role: "person" | "orchestrator"; text: string; ts: number };
export type Draft = {
  id: string; status: string; flow: string; task_id: string; base_version: number; spec: Spec; yaml: string;
  asks: Record<string, string>; problems: string[]; ready: boolean; messages: Message[]; updated: number;
  reply?: string;
};
export type Task = {
  id: string; name: string; flow: string; status: string; version: number; goal: string; trigger: string;
  scheduled: boolean; next_due: number | null; last_run: string; updated: number;
};
export type RunSummary = {
  id: string; task: string; task_id: string; version: number; status: string; trigger: string; step: number;
  steps_total: number; created: number; started: number; ended: number; error: string;
  ask: { kind: string; what: string; rule: string; text: string } | null;
};
export type Attempt = { attempt: number; status: string; started: number; ended: number | null; report: string; gate: string };
export type Event = { ts: number; ref: string; kind: string; detail: string };
export type Job = {
  id: string; run: string; status: string; command: string; why: string; created: number; started: number | null;
  ended: number | null; exit_code: number | null; seconds: number | null; log_tail: string;
};
export type Run = RunSummary & {
  steps: { n: number; title: string; model: string; attempts: Attempt[] }[]; result: string; events: Event[];
  workspace: string; activity: { ts: number; kind: string; detail: string } | null; notes: string[]; jobs: Job[];
};
export type Progress = {
  run: string; status: string; step: number; steps_total: number; seconds_since_activity: number | null;
  last_activity: string; tool_calls: number; model_calls: number; files_changed: string[]; quiet_note: string;
  looping_note: string; recent: { ts: number; kind: string; detail: string }[]; machine: string;
};
export type TaskStats = { runs: number; done: number; needs_you: number; failed: number; cancelled: number; typical_s: number | null };
export type TaskDetail = Task & { yaml: string; spec: Spec; stats: TaskStats; runs: RunSummary[] };
export type Rules = {
  permissions: { ask?: Record<string, string[]>; deny?: Record<string, string[]>; error?: string };
  permissions_file: string;
  recipe: { id: string; failure: string; seen: string; rule: string; where: string }[];
};
export type Activity = { ts: number; ref: string; kind: string; detail: string };
export type Machine = {
  holder: { kind: string; ref: string; model: string; for_s: number; note: string } | null;
  waiting: { kind: string; ref: string; model: string; waited_s: number; note: string }[];
  summary: string;
};
export type Flow = {
  name: string; description: string; when: string; model: string; params: Record<string, string>; steps: string[];
  tools: string[];
};

// What a status means to a person, everywhere it is shown.
export const SAY: Record<string, string> = {
  queued: "Queued", waiting: "Waiting for the machine", running: "Running", parked: "Parked", asking: "Asking you",
  done: "Done", failed: "Failed", timed_out: "Out of time", cancelled: "Cancelled", needs_you: "Needs you",
};
export const ATTENTION = new Set(["asking", "needs_you", "failed", "parked"]);

// A run's step as a row of beads; shared by the task page, the runs page and home.
export function beads(r: RunSummary): string[] {
  return Array.from({ length: r.steps_total }, (_, i) =>
    r.status === "done" || i < r.step - 1 ? "done" : i === r.step - 1 ? r.status : "");
}

export async function call<T>(verb: string, args: Record<string, unknown> = {}): Promise<T> {
  const r = await fetch(`/api/v/${verb}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(args),
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json()).detail ?? detail; } catch { /* keep the status */ }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export function stream(onChange: (e: Event) => void, onMachine: (m: Machine) => void): () => void {
  let since = Date.now() / 1000;
  let es: EventSource | null = null;
  let closed = false;
  const open = () => {
    es = new EventSource(`/api/stream?since=${since}`);
    es.addEventListener("change", (m) => {
      const e = JSON.parse((m as MessageEvent).data) as Event;
      since = Math.max(since, e.ts);
      onChange(e);
    });
    es.addEventListener("machine", (m) => onMachine(JSON.parse((m as MessageEvent).data)));
    es.onerror = () => { es?.close(); if (!closed) setTimeout(open, 2000); };
  };
  open();
  return () => { closed = true; es?.close(); };
}

export const LIVE = new Set(["queued", "waiting", "running", "parked", "asking"]);

export function ago(ts?: number | null): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function when(ts?: number | null): string {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit", month: "short", day: "numeric" });
}

export function duration(s: number): string {
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}
