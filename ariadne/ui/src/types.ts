export interface Flow {
  name: string;
  when: string;
}

export interface Model {
  name: string;
  kind: string;
  about: string;
  size_gb: number;
  installed: boolean;
}

export interface Choices {
  flows: Flow[];
  models: Model[];
}

export interface Gate {
  type: string;
  text: string;
}

export interface Step {
  n: number;
  text: string;
  model: string;
}

export interface Sections {
  mission: string;
  steps: Step[];
  checks: string[];
  risks: string[];
  questions: string[];
}

export type Action = "approve" | "revise" | "cancel" | "set_gates";

export interface TaskDoc {
  id: string;
  status: string;
  label: string;
  brief: string;
  flow: string;
  model: string;
  session: string;
  workspace: string;
  gates: Gate[];
  document: string;
  sections: Sections;
  models: string;
  report: string;
  error: string;
  events: string[];
  actions: Action[];
  next: string;
  card: string;
}

export interface SessionTask {
  id: string;
  status: string;
  label: string;
  flow: string;
  model: string;
  text: string[];
}

export interface Session {
  name: string;
  flow: string;
  model: string;
  workspace: string;
  segment: number | null;
  updated: number;
  summary: string;
  waiting: number;
  tasks: SessionTask[];
}

export interface InboxRunning {
  id: string;
  status: string;
  label: string;
  text: string[];
}

export interface InboxRecent {
  id: string;
  status: string;
  label: string;
}

export interface Inbox {
  waiting: TaskDoc[];
  running: InboxRunning[];
  stale: string[];
  recent: InboxRecent[];
  worker: boolean;
  text: string;
}

export interface SseEvent {
  task_id: string;
  ts: number;
  kind: string;
  detail: string;
}

export interface ChatMsg {
  who: "you" | "it";
  text: string;
}