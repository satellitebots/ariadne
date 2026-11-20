import { useState, useRef, useEffect } from "react";

interface ActivityStreamProps {
  events: string[];
}

export default function ActivityStream({ events }: ActivityStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);
  const [showJump, setShowJump] = useState(false);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    setFollow(atBottom);
    setShowJump(!atBottom);
  };

  useEffect(() => {
    if (follow && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [events, follow]);

  const jumpToLatest = () => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
      setFollow(true);
      setShowJump(false);
    }
  };

  if (!events || events.length === 0) {
    return <p className="muted small">No activity yet.</p>;
  }

  return (
    <div className="activity-wrapper">
      <div className="activity-stream" ref={containerRef} onScroll={handleScroll}>
        {events.map((ev, i) => (
          <div key={i} className="activity-line">
            {ev}
          </div>
        ))}
      </div>
      {showJump && (
        <button className="jump-chip" onClick={jumpToLatest} title="Jump to latest">
          ↓ Latest
        </button>
      )}
    </div>
  );
}