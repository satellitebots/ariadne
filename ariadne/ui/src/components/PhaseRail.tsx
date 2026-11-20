
import { PHASES, phaseInfo } from "../phases";

interface PhaseRailProps {
  status: string;
}

export default function PhaseRail({ status }: PhaseRailProps) {
  const info = phaseInfo(status);
  return (
    <ol className="phase-rail" aria-label="Task phases">
      {PHASES.map((phase, i) => {
        let cls = "future";
        let mark = "○";
        if (info.complete || i < info.current) {
          cls = "done";
          mark = "✓";
        } else if (i === info.current) {
          cls = info.failed ? "current failed" : "current";
          mark = info.failed ? "✗" : "●";
        }
        return (
          <li key={phase} className={"phase " + cls} title={phase}>
            <span className="phase-mark">{mark}</span>
            <span className="phase-label">{phase}</span>
          </li>
        );
      })}
    </ol>
  );
}