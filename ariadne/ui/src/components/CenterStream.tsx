
import type { Session, TaskDoc } from "../types";
import { statusLabel } from "../phases";
import TaskCard from "./TaskCard";
import TaskDocument from "./TaskDocument";
import EmptyState from "./EmptyState";

interface CenterStreamProps {
  session: Session | null;
  task: TaskDoc | null;
  onOpenTask: (id: string, sessionId: string) => void;
  onVerb: (verb: string, tid: string) => void;
}

export default function CenterStream({ session, task, onOpenTask, onVerb }: CenterStreamProps) {
  if (!session) {
    return (
      <EmptyState
        title="Choose a session, or start one"
        actionLabel="Give the task"
        onAction={() => document.querySelector<HTMLTextAreaElement>("[data-composer-input]")?.focus()}
      />
    );
  }

  return (
    <div className="center-stream">
      <div className="session-head">
        <h2 className="session-title">Session: {session.name}</h2>
        <span className="session-meta mono">
          {session.flow || "no flow"}{session.model ? ` · ${session.model}` : ""}
        </span>
      </div>

      {session.tasks.length === 0 ? (
        <EmptyState title="No tasks in this session yet." actionLabel="Give the task" onAction={() => document.querySelector<HTMLTextAreaElement>("[data-composer-input]")?.focus()} />
      ) : (
        <ol className="task-list">
          {session.tasks.map((t) => (
            <TaskCard
              key={t.id}
              id={t.id}
              intent={t.text && t.text[0] ? t.text[0] : t.id}
              label={statusLabel(t.status)}
              flow={t.flow}
              model={t.model}
              active={task?.id === t.id}
              onOpen={() => onOpenTask(t.id, session.name)}
            />
          ))}
        </ol>
      )}

      {task && <TaskDocument doc={task} onVerb={onVerb} />}
    </div>
  );
}