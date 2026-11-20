import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, eventsUrl } from "./api";
import type { Choices, Inbox, Session, TaskDoc, SseEvent, ChatMsg } from "./types";
import Header from "./components/Header";
import SessionRail from "./components/SessionRail";
import CenterStream from "./components/CenterStream";
import InboxView from "./components/InboxView";
import Composer from "./components/Composer";
import CommandPalette, { type CommandItem } from "./components/CommandPalette";

type View = "home" | "inbox";

export default function App() {
  const [choices, setChoices] = useState<Choices | null>(null);
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [session, setSession] = useState<string | null>(null);
  const [task, setTask] = useState<TaskDoc | null>(null);
  const [view, setView] = useState<View>("home");
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [error, setError] = useState("");
  const [occupied, setOccupied] = useState(false);
  const [busyMsg, setBusyMsg] = useState("");
  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [loading, setLoading] = useState(true);

  const sinceRef = useRef(0);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const taskRef = useRef<TaskDoc | null>(null);
  const errorTimer = useRef<number | undefined>(undefined);

  const fail = useCallback((e: unknown) => {
    const msg = e instanceof Error ? e.message : String(e);
    setError(msg);
    if (errorTimer.current) window.clearTimeout(errorTimer.current);
    errorTimer.current = window.setTimeout(() => setError(""), 8000);
  }, []);

  const loadInbox = useCallback(async () => {
    try {
      const box = await api.inbox();
      setInbox(box);
      const isBusy = box.worker && box.running.some((r) => r.status === "planning" || r.status === "executing");
      setOccupied(isBusy);
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await api.sessions());
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  const loadTask = useCallback(async (id: string) => {
    try {
      const doc = await api.task(id);
      setTask(doc);
      taskRef.current = doc;
    } catch (e) {
      fail(e);
    }
  }, [fail]);

  const openSession = useCallback((name: string) => {
    setSession(name);
    setTask(null);
    taskRef.current = null;
  }, []);

  const openTask = useCallback(
    (id: string, sessionId?: string) => {
      if (sessionId && sessionId !== session) {
        setSession(sessionId);
      }
      loadTask(id);
    },
    [session, loadTask]
  );

  // Initial load
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [ch, box, sess] = await Promise.all([api.choices(), api.inbox(), api.sessions()]);
        if (cancelled) return;
        setChoices(ch);
        setInbox(box);
        setSessions(sess);
        const isBusy = box.worker && box.running.some((r) => r.status === "planning" || r.status === "executing");
        setOccupied(isBusy);
      } catch (e) {
        fail(e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [fail]);

  // SSE stream
  useEffect(() => {
    const es = new EventSource(eventsUrl(sinceRef.current));
    let timer: number | undefined;
    es.onmessage = (m) => {
      try {
        const ev = JSON.parse(m.data) as SseEvent;
        sinceRef.current = Math.max(sinceRef.current, Number(ev.ts) || 0);
        if (timer) window.clearTimeout(timer);
        timer = window.setTimeout(() => {
          loadInbox();
          loadSessions();
          const cur = taskRef.current;
          if (cur && ev.task_id === cur.id) loadTask(cur.id);
        }, 400);
      } catch { /* keepalive or partial frame */ }
    };
    es.onerror = () => { /* EventSource auto-reconnects */ };
    return () => { es.close(); if (timer) window.clearTimeout(timer); };
  }, [loadInbox, loadSessions, loadTask]);

  // Verb actions
  const doVerb = useCallback(
    async (verb: string, tid: string) => {
      try {
        let doc: TaskDoc;
        switch (verb) {
          case "approve":
            doc = await api.approve(tid);
            break;
          case "revise": {
            const fb = prompt("What should change in the plan?");
            if (!fb) return;
            doc = await api.revise(tid, fb);
            break;
          }
          case "set_gates": {
            const txt = prompt("Check gates, one per line:");
            if (txt === null) return;
            const gates = txt.split("\n").map((g) => g.trim()).filter(Boolean);
            doc = await api.gates(tid, gates);
            break;
          }
          case "cancel":
            if (!confirm(`Cancel task ${tid}?`)) return;
            doc = await api.cancel(tid);
            break;
          case "steer": {
            const fb = prompt("Guidance for the task:");
            if (!fb) return;
            doc = await api.steer(tid, fb);
            break;
          }
          default:
            return;
        }
        setTask(doc);
        taskRef.current = doc;
        loadInbox();
        loadSessions();
      } catch (e) {
        fail(e);
      }
    },
    [fail, loadInbox, loadSessions]
  );

  const submitTask = useCallback(
    async (body: { text: string; flow: string; model: string; workspace: string; session: string; gates: string[] }) => {
      try {
        const doc = await api.submit(body);
        setBusyMsg("");
        openSession(doc.session);
        loadTask(doc.id);
        loadInbox();
        loadSessions();
      } catch (e) {
        if (e instanceof ApiError && /hardware occupied/i.test(e.message)) {
          setBusyMsg(e.message);
        }
        fail(e);
      }
    },
    [fail, loadInbox, loadSessions, loadTask, openSession]
  );

  const chatSend = useCallback(
    async (message: string) => {
      if (!message.trim()) return;
      setChat((prev) => [...prev, { who: "you", text: message }]);
      try {
        const res = await api.chat(message, session ?? "");
        setChat((prev) => [...prev, { who: "it", text: res.reply }]);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setChat((prev) => [...prev, { who: "it", text: msg }]);
      }
    },
    [session]
  );

  const focusComposer = useCallback(() => {
    composerRef.current?.focus();
  }, []);

  // Command palette commands
  const commands: CommandItem[] = [
    { id: "new-task", label: "New task", hint: "Focus composer", run: focusComposer },
    { id: "inbox", label: "Open inbox", hint: "View decisions", run: () => setView("inbox") },
  ];
  for (const s of sessions) {
    commands.push({ id: `sess-${s.name}`, label: `Go to: ${s.name}`, hint: "Session", run: () => { setView("home"); openSession(s.name); } });
  }
  if (task) {
    const tid = task.id;
    if (task.actions.includes("approve")) commands.push({ id: "cmd-approve", label: `Approve ${tid}`, run: () => doVerb("approve", tid) });
    if (task.actions.includes("revise")) commands.push({ id: "cmd-revise", label: `Send back ${tid}`, run: () => doVerb("revise", tid) });
    if (task.actions.includes("cancel")) commands.push({ id: "cmd-cancel", label: `Cancel ${tid}`, run: () => doVerb("cancel", tid) });
    if (task.actions.includes("set_gates")) commands.push({ id: "cmd-gates", label: `Set gates ${tid}`, run: () => doVerb("set_gates", tid) });
    if (task.status === "planning" || task.status === "executing") commands.push({ id: "cmd-steer", label: `Steer ${tid}`, run: () => doVerb("steer", tid) });
  }

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
        return;
      }
      if (e.key === "Escape") {
        setPaletteOpen(false);
        return;
      }
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable)) return;
      if (paletteOpen) return;

      // j/k navigation
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const dir = e.key === "j" ? 1 : -1;
        if (view === "inbox" && inbox) {
          // handled in InboxView via ref
        }
        // For session rail
        setSession((prev) => {
          if (!sessions.length) return prev;
          const idx = sessions.findIndex((s) => s.name === prev);
          const next = Math.max(0, Math.min(sessions.length - 1, (idx === -1 ? 0 : idx) + dir));
          return sessions[next].name;
        });
      }
      if (e.key === "Enter") {
        if (session && view === "home") {
          const s = sessions.find((s) => s.name === session);
          if (s && s.tasks.length > 0) {
            openTask(s.tasks[0].id, session);
          }
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [sessions, session, view, paletteOpen, inbox, openTask]);

  const activeSessionData = session ? sessions.find((s) => s.name === session) ?? null : null;

  if (loading) {
    return (
      <div className="app loading">
        <div className="header-skeleton" />
        <div className="body">
          <div className="rail-skeleton">
            <div className="skel-row" /><div className="skel-row" /><div className="skel-row" /><div className="skel-row" />
          </div>
          <div className="center-skeleton">
            <div className="skel-block" /><div className="skel-block" />
          </div>
        </div>
        <div className="composer-skeleton" />
      </div>
    );
  }

  return (
    <div className="app">
      <Header
        view={view}
        setView={setView}
        inboxCount={inbox?.waiting.length ?? 0}
        worker={inbox?.worker ?? false}
        occupied={occupied}
        onPaletteToggle={() => setPaletteOpen((o) => !o)}
      />

      {busyMsg && (
        <div className="occupied-strip" role="alert">
          <span className="occupied-icon">⚠</span>
          <span>{busyMsg}</span>
          {/* TODO: Add a Stop button when the backend exposes a parking/stop endpoint */}
          <button className="btn btn-secondary" disabled title="Stop endpoint not yet available from backend">
            Stop
          </button>
        </div>
      )}

      <div className="body">
        <SessionRail
          sessions={sessions}
          active={session}
          onSelect={openSession}
        />

        <main className="center">
          {view === "inbox" && inbox ? (
            <InboxView
              inbox={inbox}
              onOpenTask={openTask}
              onVerb={(v, tid) => doVerb(v, tid)}
            />
          ) : (
            <CenterStream
              session={activeSessionData}
              task={task}
              onOpenTask={openTask}
              onVerb={(v, tid) => doVerb(v, tid)}
            />
          )}
        </main>
      </div>

      {error && <div className="toast-error" role="alert">{error}</div>}

      <Composer
        choices={choices}
        session={session}
        sessions={sessions}
        chat={chat}
        textareaRef={composerRef}
        onSubmit={submitTask}
        onChat={chatSend}
      />

      {paletteOpen && (
        <CommandPalette
          commands={commands}
          onClose={() => setPaletteOpen(false)}
        />
      )}
    </div>
  );
}