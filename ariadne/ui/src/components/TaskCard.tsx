

interface TaskCardProps {
  id: string;
  intent: string;
  label: string;
  flow: string;
  model: string;
  active: boolean;
  onOpen: () => void;
}

export default function TaskCard({ id, intent, label, flow, model, active, onOpen }: TaskCardProps) {
  return (
    <li>
      <button className={"task-card" + (active ? " active" : "")} onClick={onOpen} title={id}>
        <div className="task-card-line1">
          <span className="task-intent">{intent}</span>
          <span className={"status-pill status-" + label}>{label}</span>
        </div>
        <div className="task-card-line2 mono">
          {flow && <span>{flow}</span>}
          {flow && model && <span className="dot-sep">·</span>}
          {model && <span>{model}</span>}
        </div>
      </button>
    </li>
  );
}