
import type { Session } from "../types";
import SessionRow from "./SessionRow";

interface SessionRailProps {
  sessions: Session[];
  active: string | null;
  onSelect: (name: string) => void;
}

export default function SessionRail({ sessions, active, onSelect }: SessionRailProps) {
  return (
    <aside className="rail" aria-label="Sessions">
      <div className="rail-head">
        <h2 className="rail-title">Sessions</h2>
      </div>

      {sessions.length === 0 ? (
        <p className="rail-empty">No sessions yet. Start one from the composer below.</p>
      ) : (
        <ul className="session-list">
          {sessions.map((s) => (
            <SessionRow
              key={s.name}
              session={s}
              active={s.name === active}
              onSelect={() => onSelect(s.name)}
            />
          ))}
        </ul>
      )}
    </aside>
  );
}