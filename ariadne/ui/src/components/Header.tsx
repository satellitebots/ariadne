

interface HeaderProps {
  view: "home" | "inbox";
  setView: (v: "home" | "inbox") => void;
  inboxCount: number;
  worker: boolean;
  occupied: boolean;
  onStop: () => void;
  onPaletteToggle: () => void;
}

export default function Header({
  view,
  setView,
  inboxCount,
  worker,
  occupied,
  onStop,
  onPaletteToggle,
}: HeaderProps) {
  return (
    <header className="header">
      <div className="brand" title="Ariadne">
        Ariadne
      </div>

      <nav className="header-nav">
        <button
          className={"nav-btn" + (view === "inbox" ? " active" : "")}
          onClick={() => setView("inbox")}
          aria-label="Inbox"
        >
          Inbox
          {inboxCount > 0 && <span className="nav-badge">{inboxCount}</span>}
        </button>
        <button
          className={"nav-btn" + (view === "home" ? " active" : "")}
          onClick={() => setView("home")}
          aria-label="Sessions"
        >
          Sessions
        </button>
      </nav>

      <div className="header-right">
        <span
          className={"worker-pill" + (occupied ? " pill-occupied" : worker ? " worker-on" : " worker-off")}
          title={occupied ? "hardware occupied" : worker ? "orchestrator listening" : "orchestrator idle"}
        >
          <span className={"worker-dot" + (occupied ? " dot-busy" : worker ? " dot-on" : " dot-off")} />
          {occupied ? "occupied" : worker ? "listening" : "idle"}
        </span>

        <button className="kbd-hint" onClick={onPaletteToggle} title="Open command palette">
          ⌘K
        </button>

        <button
          className="btn btn-stop"
          disabled={!occupied}
          onClick={onStop}
          title={occupied ? "Interrupt the running task and park it" : "Nothing is running"}
          aria-label="Stop"
        >
          Stop
        </button>
      </div>
    </header>
  );
}