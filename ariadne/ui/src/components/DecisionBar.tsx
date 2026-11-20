import { useState, useEffect } from "react";
import type { TaskDoc } from "../types";

interface DecisionBarProps {
  doc: TaskDoc;
  onVerb: (verb: string, tid: string) => void;
}

type Panel = "" | "approve" | "revise" | "set_gates" | "steer";

export default function DecisionBar({ doc, onVerb }: DecisionBarProps) {
  const [panel, setPanel] = useState<Panel>("");
  const [feedback, setFeedback] = useState("");
  const [models, setModels] = useState("");
  const [gatesText, setGatesText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPanel("");
    setFeedback("");
    setModels("");
    setGatesText("");
    setBusy(false);
  }, [doc.id, doc.status]);

  const legal = doc.actions || [];
  const isRunning = doc.status === "planning" || doc.status === "executing";

  if (legal.length === 0 && !isRunning) {
    return null;
  }

  const primaryVerb: string =
    legal.includes("approve") ? "approve" :
    legal.includes("set_gates") ? "set_gates" :
    isRunning ? "steer" : "";

  const openPanel = (v: Panel) => {
    if (v === "set_gates" && doc.gates) {
      setGatesText(doc.gates.map((g) => (g.type === "run" ? `run: ${g.text}` : g.text)).join("\n"));
    } else {
      setFeedback("");
      setModels("");
    }
    setPanel(v);
  };

  const submit = async () => {
    setBusy(true);
    try {
      switch (panel) {
        case "approve":
          onVerb("approve", doc.id);
          break;
        case "revise":
          if (feedback.trim()) {
            onVerb("revise", doc.id);
          }
          break;
        case "steer":
          if (feedback.trim()) {
            onVerb("steer", doc.id);
          }
          break;
        case "set_gates": {
          const gates = gatesText.split("\n").map((g) => g.trim()).filter(Boolean);
          if (gates.length > 0) {
            onVerb("set_gates", doc.id);
          }
          break;
        }
      }
      setPanel("");
    } finally {
      setBusy(false);
    }
  };

  const doCancel = () => {
    if (confirm(`Cancel task ${doc.id}?`)) {
      onVerb("cancel", doc.id);
    }
  };

  return (
    <div className="decision-bar">
      {panel !== "" ? (
        <div className="decision-panel">
          {panel === "approve" && (
            <div className="panel-row">
              <label className="panel-label">
                Change a step's model before locking? (e.g. 2=gemma-4-12b, all=qwen3.6-35b-a3b)
                <input
                  className="panel-input mono"
                  value={models}
                  onChange={(e) => setModels(e.target.value)}
                  placeholder="optional"
                  autoFocus
                />
              </label>
            </div>
          )}

          {(panel === "revise" || panel === "steer") && (
            <div className="panel-row">
              <label className="panel-label">
                {panel === "revise" ? "What should change in the plan?" : "Guidance for the task:"}
                <textarea
                  className="panel-textarea"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  rows={3}
                  autoFocus
                  placeholder={panel === "revise" ? "the feedback the planner must address" : "guidance delivered at next step"}
                />
              </label>
            </div>
          )}

          {panel === "set_gates" && (
            <div className="panel-row">
              <label className="panel-label">
                Check gates, one per line
                <textarea
                  className="panel-textarea mono"
                  value={gatesText}
                  onChange={(e) => setGatesText(e.target.value)}
                  rows={3}
                  autoFocus
                  placeholder="run: pytest -q"
                />
              </label>
            </div>
          )}

          <div className="panel-actions">
            <button
              className="btn btn-primary"
              onClick={submit}
              disabled={busy || (panel === "revise" && !feedback.trim()) || (panel === "steer" && !feedback.trim())}
            >
              {busy ? "..." : panel === "approve" ? "Approve" : panel === "revise" ? "Send back" : panel === "steer" ? "Steer" : "Save gates"}
            </button>
            <button className="btn btn-text" onClick={() => setPanel("")}>
              Not yet
            </button>
          </div>
        </div>
      ) : (
        <div className="decision-row">
          {legal.includes("approve") && (
            <button
              className={primaryVerb === "approve" ? "btn btn-primary" : "btn btn-text"}
              onClick={() => openPanel("approve")}
            >
              Approve
            </button>
          )}
          {legal.includes("revise") && (
            <button
              className={primaryVerb === "revise" ? "btn btn-primary" : "btn btn-text"}
              onClick={() => openPanel("revise")}
            >
              Send back
            </button>
          )}
          {legal.includes("set_gates") && (
            <button
              className={primaryVerb === "set_gates" ? "btn btn-primary" : "btn btn-text"}
              onClick={() => openPanel("set_gates")}
            >
              Set check gates
            </button>
          )}
          {isRunning && (
            <button
              className={primaryVerb === "steer" ? "btn btn-primary" : "btn btn-text"}
              onClick={() => openPanel("steer")}
            >
              Steer
            </button>
          )}
          {legal.includes("cancel") && (
            <button className="btn btn-text btn-danger" onClick={doCancel}>
              Cancel
            </button>
          )}
        </div>
      )}
    </div>
  );
}