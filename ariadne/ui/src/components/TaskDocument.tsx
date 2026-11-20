import { useRef, useState, useEffect } from "react";
import type { TaskDoc } from "../types";
import PhaseRail from "./PhaseRail";
import GateList from "./GateList";
import ActivityStream from "./ActivityStream";
import DecisionBar from "./DecisionBar";
import { statusLabel } from "../phases";

interface TaskDocumentProps {
  doc: TaskDoc;
  onVerb: (verb: string, tid: string) => void;
}

export default function TaskDocument({ doc, onVerb }: TaskDocumentProps) {
  const [tab, setTab] = useState<"backbrief" | "activity">("backbrief");
  const docRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    docRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [doc.id]);

  const hasPlan =
    doc.sections &&
    ((doc.sections.mission && doc.sections.mission.trim()) ||
      (doc.sections.steps && doc.sections.steps.length > 0));

  return (
    <article className="task-doc" ref={docRef}>
      <div className="doc-header">
        <PhaseRail status={doc.status} />
        <div className="doc-title-row">
          <h3 className="doc-title">{firstLine(doc.brief) || doc.id}</h3>
          <span className={`status-badge status-${doc.status}`}>
            {statusLabel(doc.status)}
          </span>
        </div>
        <div className="doc-meta mono">
          <span>{doc.id}</span>
          {doc.flow && <span className="meta-sep">· {doc.flow}</span>}
          {doc.model && <span className="meta-sep">· {doc.model}</span>}
          {doc.workspace && <span className="meta-sep">· {doc.workspace}</span>}
        </div>
      </div>

      <div className="doc-tabs">
        <button
          className={tab === "backbrief" ? "tab active" : "tab"}
          onClick={() => setTab("backbrief")}
        >
          Backbrief
        </button>
        <button
          className={tab === "activity" ? "tab active" : "tab"}
          onClick={() => setTab("activity")}
        >
          Activity
        </button>
      </div>

      {tab === "backbrief" && (
        <div className="doc-body">
          <section className="doc-section">
            <h4 className="section-label">Brief</h4>
            <p className="brief-text">{doc.brief}</p>
          </section>

          {doc.gates && doc.gates.length > 0 && (
            <section className="doc-section">
              <h4 className="section-label">Check Gates</h4>
              <GateList gates={doc.gates} />
            </section>
          )}

          {hasPlan ? (
            <>
              {doc.sections.mission && (
                <section className="doc-section">
                  <h4 className="section-label">Mission</h4>
                  <p className="mission-text">{doc.sections.mission}</p>
                </section>
              )}

              {doc.sections.steps && doc.sections.steps.length > 0 && (
                <section className="doc-section">
                  <h4 className="section-label">Steps</h4>
                  <ol className="steps-list">
                    {doc.sections.steps.map((s) => (
                      <li key={s.n} className="step-item">
                        <span className="step-num mono">{s.n}.</span>
                        <span className="step-text">{s.text}</span>
                        {s.model && (
                          <span className="step-model mono">model: {s.model}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              {doc.sections.checks && doc.sections.checks.length > 0 && (
                <section className="doc-section">
                  <h4 className="section-label">How the plan proves each gate</h4>
                  <ul className="checks-list">
                    {doc.sections.checks.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </section>
              )}

              {doc.sections.risks && doc.sections.risks.length > 0 && (
                <section className="doc-section">
                  <h4 className="section-label">Risks</h4>
                  <ul className="risks-list">
                    {doc.sections.risks.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </section>
              )}

              {doc.sections.questions && doc.sections.questions.length > 0 && (
                <section className="doc-section">
                  <h4 className="section-label">Questions</h4>
                  <ul className="questions-list">
                    {doc.sections.questions.map((q, i) => (
                      <li key={i}>{q}</li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          ) : (
            doc.document && (
              <section className="doc-section">
                <h4 className="section-label">Backbrief</h4>
                <pre className="doc-pre">{doc.document}</pre>
              </section>
            )
          )}

          {doc.report && (
            <section className="doc-section">
              <h4 className="section-label">{doc.status === "done" ? "Report" : "Result"}</h4>
              <pre className="doc-pre">{doc.report}</pre>
            </section>
          )}

          {doc.error && (
            <section className="doc-section error-section">
              <h4 className="section-label">Stopped</h4>
              <pre className="doc-pre error-text">{doc.error}</pre>
            </section>
          )}
        </div>
      )}

      {tab === "activity" && (
        <div className="doc-body">
          <ActivityStream events={doc.events} />
        </div>
      )}

      {doc.next && (
        <p className="next-hint">{doc.next}</p>
      )}

      <DecisionBar doc={doc} onVerb={onVerb} />
    </article>
  );
}

function firstLine(text: string): string {
  if (!text) return "";
  return text.split("\n")[0].trim();
}