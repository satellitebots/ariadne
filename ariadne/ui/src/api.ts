import type { Choices, Inbox, Session, TaskDoc } from "./types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, (body as Record<string, string>).detail ?? `${res.status} ${res.statusText}`);
  }
  return body as T;
}

export const api = {
  choices: () => request<Choices>("/api/choices"),
  inbox: () => request<Inbox>("/api/inbox"),
  sessions: () => request<Session[]>("/api/sessions?limit=25"),
  task: (id: string) => request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}`),

  submit(body: {
    text: string;
    flow: string;
    model: string;
    workspace: string;
    session: string;
    gates: string[];
  }) {
    return request<TaskDoc>("/api/tasks", { method: "POST", body: JSON.stringify(body) });
  },

  approve: (id: string, models?: string) =>
    request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}/approve`, {
      method: "POST",
      body: JSON.stringify({ models: models ?? "" }),
    }),

  revise: (id: string, feedback: string) =>
    request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}/revise`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    }),

  gates: (id: string, gates: string[]) =>
    request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}/gates`, {
      method: "POST",
      body: JSON.stringify({ gates }),
    }),

  cancel: (id: string) =>
    request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),

  steer: (id: string, feedback: string) =>
    request<TaskDoc>(`/api/tasks/${encodeURIComponent(id)}/steer`, {
      method: "POST",
      body: JSON.stringify({ feedback }),
    }),

  health: () => request<{ ok: boolean; orchestrator: boolean; occupied: boolean; parked: boolean }>("/api/health"),

  park: () => request<unknown>("/api/park", { method: "POST" }),

  createSession: (body: { name: string; flow?: string; model?: string; workspace?: string }) =>
    request<Session>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),

  deleteSession: (name: string) =>
    request<{ deleted: string }>(`/api/sessions/${encodeURIComponent(name)}`, { method: "DELETE" }),

  chat: (message: string, session: string) =>
    request<{ reply: string; session: string }>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, session }),
    }),
};

export function eventsUrl(since: number): string {
  return `/api/events?since=${since}`;
}