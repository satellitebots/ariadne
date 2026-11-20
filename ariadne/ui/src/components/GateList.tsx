
import type { Gate } from "../types";

interface GateListProps {
  gates: Gate[];
}

export default function GateList({ gates }: GateListProps) {
  if (!gates || gates.length === 0) return null;
  return (
    <ul className="gate-list">
      {gates.map((g, i) => {
        const isRun = g.type === "run";
        return (
          <li key={i} className={"gate" + (isRun ? " gate-run" : " gate-review")}>
            {isRun ? (
              <>
                <span className="gate-dot" />
                <code className="mono">{g.text}</code>
              </>
            ) : (
              <span className="gate-sentence">{g.text}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}