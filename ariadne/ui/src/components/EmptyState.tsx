

interface EmptyStateProps {
  title: string;
  actionLabel?: string;
  onAction?: () => void;
}

export default function EmptyState({ title, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <p className="empty-text">{title}</p>
      {actionLabel && onAction && (
        <button className="btn btn-primary" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}