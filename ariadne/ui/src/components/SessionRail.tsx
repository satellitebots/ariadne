import { useState } from "react";
import type { Choices, Session } from "../types";
import SessionRow from "./SessionRow";

interface SessionRailProps {
  sessions: Session[];
  choices: Choices | null;
  active: string | null;
  onSelect: (name: string) => void;
  onCreate: (body: { name: string; flow: string; model: string; workspace: string }) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}

export default function SessionRail({ sessions, choices, active, onSelect, onCreate, onDelete }: SessionRailProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [flow, setFlow] = useState("");
  const [model, setModel] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr("");
    try {
      await onCreate({ name: name.trim(), flow, model, workspace });
      setName(""); setFlow(""); setModel(""); setWorkspace(""); setOpen(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const flows = choices?.flows ?? [];
  const models = choices?.models ?? [];

  return (
    <aside className="rail" aria-label="Sessions">
      <div className="rail-head">
        <h2 className="rail-title">Sessions</h2>
        <button className="rail-add" onClick={() => setOpen((o) => !o)} aria-label="New session">
          + New session
        </button>
      </div>

      {open && (
        <form className="new-session" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <input autoFocus value={name} placeholder="Session name (project or folder)"
                 onChange={(e) => setName(e.target.value)} />
          <select value={flow} onChange={(e) => setFlow(e.target.value)}>
            <option value="">flow default</option>
            {flows.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
          </select>
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">model default</option>
            {models.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
          <input value={workspace} placeholder="Workspace (optional)"
                 onChange={(e) => setWorkspace(e.target.value)} />
          <div className="new-session-actions">
            <button className="btn" type="submit" disabled={!name.trim()}>Create</button>
            <button className="btn btn-secondary" type="button" onClick={() => setOpen(false)}>Close</button>
          </div>
          {err && <p className="form-error">{err}</p>}
        </form>
      )}

      {sessions.length === 0 && !open ? (
        <p className="rail-empty">No sessions yet. Start one above.</p>
      ) : (
        <ul className="session-list">
          {sessions.map((s) => (
            <li key={s.name} className="session-row-wrap">
              <SessionRow session={s} active={s.name === active} onSelect={() => onSelect(s.name)} />
              <button
                className="session-del"
                aria-label={"Delete " + s.name}
                title="Delete session"
                onClick={() => {
                  if (window.confirm("Delete session " + s.name + "?")) {
                    onDelete(s.name).catch((e) => window.alert(e instanceof Error ? e.message : String(e)));
                  }
                }}
              >
                x
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
