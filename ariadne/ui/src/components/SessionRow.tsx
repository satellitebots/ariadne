
import type { Session } from "../types";
import { statusLabel } from "../phases";

interface SessionRowProps {
  session: Session;
  active: boolean;
  onSelect: () => void;
}

function firstTaskLine(s: Session): string {
  if (!s.tasks || s.tasks.length === 0) return "";
  return (s.tasks[0].text && s.tasks[0].text[0]) || statusLabel(s.tasks[0].status);
}

export default function SessionRow({ session, active, onSelect }: SessionRowProps) {
  const line = firstTaskLine(session);
  return (
    <li>
      <button
        className={"session-row" + (active ? " active" : "")}
        onClick={onSelect}
        title={session.summary || session.name}
      >
        <div className="session-row-main">
          <span className="session-name">{session.name}</span>
          {session.waiting > 0 && <span className="unread-dot" aria-label={`${session.waiting} need you`} />}
        </div>
        <div className="session-row-sub">
          <span className="session-flow">{session.flow || "no flow yet"}</span>
          {session.model && <span className="session-model"> · {session.model}</span>}
        </div>
        {line && <div className="session-row-event">{line.slice(0, 48)}</div>}
      </button>
    </li>
  );
}