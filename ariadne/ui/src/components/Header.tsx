

interface HeaderProps {
  view: "home" | "inbox";
  setView: (v: "home" | "inbox") => void;
  inboxCount: number;
  worker: boolean;
  occupied: boolean;
  onPaletteToggle: () => void;
}

export default function Header({
  view,
  setView,
  inboxCount,
  worker,
  occupied,
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
          className={"worker-pill" + (worker ? " worker-on" : " worker-off")}
          title={occupied ? "hardware occupied" : worker ? "worker running" : "worker idle"}
        >
          <span className={"worker-dot" + (worker ? " dot-on" : " dot-off")} />
          {occupied ? "occupied" : worker ? "working" : "idle"}
        </span>

        <button className="kbd-hint" onClick={onPaletteToggle} title="Open command palette">
          ⌘K
        </button>

        {/* TODO: Stop/park the worker. The rulebook exposes `service.busy`, but the HTTP
            server does not currently expose a parking/stop endpoint, so this stays a
            non-functional affordance until the backend adds one. Do not invent a route. */}
        <button
          className="btn btn-stop"
          disabled
          title="Stop is not exposed by the backend yet"
          aria-label="Stop"
        >
          Stop
        </button>
      </div>
    </header>
  );
}