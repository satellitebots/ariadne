import { useState, useCallback, type RefObject, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { Choices, ChatMsg, Session } from "../types";

interface ComposerProps {
  choices: Choices | null;
  session: string | null;
  sessions: Session[];
  chat: ChatMsg[];
  textareaRef: RefObject<HTMLTextAreaElement>;
  onSubmit: (body: {
    text: string;
    flow: string;
    model: string;
    workspace: string;
    session: string;
    gates: string[];
  }) => void;
  onChat: (message: string) => void;
}

export default function Composer({
  choices,
  session,
  sessions,
  chat,
  textareaRef,
  onSubmit,
  onChat,
}: ComposerProps) {
  const [mode, setMode] = useState<"task" | "chat">("task");
  const [text, setText] = useState("");
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [flow, setFlow] = useState("");
  const [model, setModel] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [gates, setGates] = useState("");
  const [sessionOverride, setSessionOverride] = useState("");
  const [sending, setSending] = useState(false);
  const [chatVisible, setChatVisible] = useState(false);

  const activeSession = sessions.find((s) => s.name === session);
  const defaultWorkspace = activeSession?.workspace || "";
  const targetSession = sessionOverride || session || "";

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    }
  }, [textareaRef]);

  const handleSend = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || sending) return;

    if (mode === "task") {
      if (!flow || !model) {
        setDetailsOpen(true);
        return;
      }
      setSending(true);
      const gateList = gates.split("\n").map((g) => g.trim()).filter(Boolean);
      onSubmit({
        text: trimmed,
        flow,
        model,
        workspace: workspace.trim() || defaultWorkspace,
        session: targetSession,
        gates: gateList,
      });
      setText("");
      setSending(false);
      resize();
    } else {
      onChat(trimmed);
      setText("");
      setChatVisible(true);
      setSending(false);
      resize();
    }
  }, [text, mode, sending, flow, model, gates, workspace, defaultWorkspace, targetSession, onSubmit, onChat, resize]);

  const handleKeyDown = useCallback(
    (e: ReactKeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <div className="composer-area">
      {chatVisible && chat.length > 0 && (
        <div className="chat-panel">
          <div className="chat-log">
            {chat.map((msg, i) => (
              <div key={i} className={`chat-bubble chat-${msg.who}`}>
                {msg.text}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="composer">
        <div className="composer-tabs">
          <button
            className={mode === "task" ? "mode-tab active" : "mode-tab"}
            onClick={() => setMode("task")}
          >
            Task
          </button>
          <button
            className={mode === "chat" ? "mode-tab active" : "mode-tab"}
            onClick={() => setMode("chat")}
          >
            Chat
          </button>
        </div>

        <div className="composer-input-row">
          <textarea
            ref={textareaRef}
            data-composer-input
            className="composer-textarea"
            rows={1}
            placeholder={
              mode === "task"
                ? "What should be true when it is done?"
                : "Ask about this session or describe the work…"
            }
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              resize();
            }}
            onKeyDown={handleKeyDown}
          />
          <button
            className="btn btn-primary composer-send"
            onClick={handleSend}
            disabled={!text.trim() || sending}
            title="⌘Enter"
          >
            {sending ? "…" : "Send"}
          </button>
        </div>

        <div className="composer-footer">
          <button
            className="details-toggle"
            onClick={() => setDetailsOpen((o) => !o)}
            aria-expanded={detailsOpen}
          >
            {detailsOpen ? "▾ Details" : "▸ Details"}
          </button>
          <span className="composer-hint">⌘Enter to send</span>
        </div>

        {detailsOpen && (
          <div className="composer-details">
            <div className="detail-row">
              <label className="detail-label">Flow</label>
              <select
                className="detail-select"
                value={flow}
                onChange={(e) => setFlow(e.target.value)}
              >
                <option value="">choose a flow…</option>
                {choices?.flows.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.name} — {f.when}
                  </option>
                ))}
              </select>
            </div>
            <div className="detail-row">
              <label className="detail-label">Model</label>
              <select
                className="detail-select"
                value={model}
                onChange={(e) => setModel(e.target.value)}
              >
                <option value="">choose a model…</option>
                {choices?.models.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                    {m.installed ? "" : " (not installed)"}
                  </option>
                ))}
              </select>
            </div>
            <div className="detail-row">
              <label className="detail-label">Workspace</label>
              <input
                className="detail-input mono"
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
                placeholder={defaultWorkspace || "path to repo"}
              />
            </div>
            <div className="detail-row">
              <label className="detail-label">Session</label>
              <input
                className="detail-input"
                value={sessionOverride}
                onChange={(e) => setSessionOverride(e.target.value)}
                placeholder={session || "workspace folder name"}
              />
            </div>
            <div className="detail-row">
              <label className="detail-label">Gates</label>
              <textarea
                className="detail-input mono"
                rows={2}
                value={gates}
                onChange={(e) => setGates(e.target.value)}
                placeholder="run: pytest -q"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}