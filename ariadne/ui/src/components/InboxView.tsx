import { useState, useEffect, useCallback } from "react";
import type { Inbox, TaskDoc } from "../types";
import { statusLabel } from "../phases";
import EmptyState from "./EmptyState";

interface InboxViewProps {
  inbox: Inbox;
  onOpenTask: (id: string, sessionId?: string) => void;
  onVerb: (verb: string, tid: string) => void;
}

export default function InboxView({ inbox, onOpenTask, onVerb }: InboxViewProps) {
  const [selected, setSelected] = useState(0);

  useEffect(() => {
    setSelected(0);
  }, [inbox.waiting.length]);

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;

      if (e.key === "j") {
        e.preventDefault();
        setSelected((s) => Math.min(s + 1, inbox.waiting.length - 1));
      } else if (e.key === "k") {
        e.preventDefault();
        setSelected((s) => Math.max(s - 1, 0));
      } else if (e.key === "Enter" && inbox.waiting[selected]) {
        e.preventDefault();
        const t = inbox.waiting[selected];
        onOpenTask(t.id, t.session);
      }
    },
    [inbox.waiting, selected, onOpenTask]
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  if (inbox.waiting.length === 0 && inbox.running.length === 0) {
    return <EmptyState title="Nothing needs you." />;
  }

  return (
    <div className="inbox-view">
      {inbox.waiting.length > 0 && (
        <section className="inbox-section">
          <h3 className="inbox-section-title">Needs you ({inbox.waiting.length})</h3>
          <ul className="inbox-list">
            {inbox.waiting.map((t, i) => (
              <InboxCard
                key={t.id}
                doc={t}
                selected={i === selected}
                onSelect={() => setSelected(i)}
                onOpen={() => onOpenTask(t.id, t.session)}
                onVerb={onVerb}
              />
            ))}
          </ul>
        </section>
      )}

      {inbox.running.length > 0 && (
        <section className="inbox-section">
          <h3 className="inbox-section-title">Running ({inbox.running.length})</h3>
          <ul className="inbox-list muted-list">
            {inbox.running.map((r) => (
              <li key={r.id} className="inbox-item running">
                <span className="inbox-intent">{r.text[0] || r.id}</span>
                <span className="status-badge status-{r.status}">{statusLabel(r.status)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {inbox.stale.length > 0 && (
        <section className="inbox-section">
          <h3 className="inbox-section-title warn">Stopped, no worker</h3>
          <ul className="inbox-list muted-list">
            {inbox.stale.map((id) => (
              <li key={id} className="inbox-item stale">
                <span className="mono">{id}</span>
                <span className="muted small">needs attention</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

interface InboxCardProps {
  doc: TaskDoc;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onVerb: (verb: string, tid: string) => void;
}

function InboxCard({ doc, selected, onSelect, onOpen, onVerb }: InboxCardProps) {
  const primaryAction =
    doc.actions.includes("approve") ? "approve" :
    doc.actions.includes("set_gates") ? "set_gates" :
    null;

  return (
    <li
      className={"inbox-card" + (selected ? " selected" : "")}
      onClick={onSelect}
      tabIndex={0}
    >
      <div className="inbox-card-header">
        <span className="inbox-intent">{(doc.brief || doc.id).split("\n")[0].slice(0, 80)}</span>
        <span className={`status-badge status-${doc.status}`}>{statusLabel(doc.status)}</span>
      </div>
      {doc.next && <p className="inbox-why">{doc.next}</p>}
      <div className="inbox-card-actions">
        {primaryAction && (
          <button
            className="btn btn-primary btn-small"
            onClick={(e) => {
              e.stopPropagation();
              onVerb(primaryAction, doc.id);
            }}
          >
            {primaryAction === "approve" ? "Approve" : "Set check gates"}
          </button>
        )}
        <button className="btn btn-text btn-small" onClick={(e) => { e.stopPropagation(); onOpen(); }}>
          Open
        </button>
      </div>
    </li>
  );
}