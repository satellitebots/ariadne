import { useEffect, useRef, useState } from "react";
import { call, type Draft, type Message } from "../api";
import type { Selection } from "../App";

type ChatOut = { conversation: string; reply: string; messages: Message[] };

// The orchestrator: bound to the open draft when there is one, otherwise a general conversation that can start,
// park, steer and resume runs. It waits for the machine like everything else; the bar at the top says who holds it.
export default function Orchestrator({ draftId, tick }: { draftId: string; go: (s: Selection) => void; tick: number }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [conversation, setConversation] = useState(() => sessionStorageGet("ariadne.conversation"));
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (draftId) {
      call<Draft>("draft_show", { draft: draftId }).then((d) => setMessages(d.messages)).catch(() => {});
    } else if (!conversation) {
      setMessages([]);
    }
  }, [draftId, tick, conversation]);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages, busy]);

  async function send() {
    const msg = text.trim();
    if (!msg) return;
    setBusy(true); setErr(""); setText("");
    setMessages((m) => [...m, { role: "person", text: msg, ts: Date.now() / 1000 }]);
    try {
      if (draftId) {
        const d = await call<Draft>("say", { draft: draftId, message: msg });
        setMessages(d.messages);
      } else {
        const out = await call<ChatOut>("chat", { message: msg, conversation });
        setConversation(out.conversation);
        sessionStorageSet("ariadne.conversation", out.conversation);
        setMessages(out.messages);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <aside className="orch" aria-label="Orchestrator">
      <header>
        <h2>Orchestrator</h2>
        <p className="dim small">{draftId ? "Working on this draft with you." : "Defines tasks and manages runs. It never does the work itself."}</p>
        {!draftId && conversation && (
          <button className="link small" onClick={() => { setConversation(""); sessionStorageSet("ariadne.conversation", ""); setMessages([]); }}>
            New conversation
          </button>
        )}
      </header>
      <div className="msgs">
        {messages.length === 0 && (
          <p className="dim small">{draftId ? "Tell it what is missing or what to change, e.g. \"use GOOGL, weekdays at 7\"."
                                            : "Ask what is running, or say what you want done."}</p>
        )}
        {messages.map((m, i) => <div key={i} className={`msg ${m.role}`}>{m.text}</div>)}
        {busy && <div className="msg orchestrator thinking">Thinking… (it waits if a run holds the machine)</div>}
        <div ref={end} />
      </div>
      {err && <p className="banner error small">{err}</p>}
      <form onSubmit={(e) => { e.preventDefault(); send(); }}>
        <textarea value={text} rows={3} onChange={(e) => setText(e.target.value)} disabled={busy}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder={draftId ? "Reply to the orchestrator" : "Message the orchestrator"} aria-label="Message" />
        <button type="submit" className="primary" disabled={busy || !text.trim()}>Send</button>
      </form>
    </aside>
  );
}

function sessionStorageGet(k: string): string {
  try { return sessionStorage.getItem(k) || ""; } catch { return ""; }
}
function sessionStorageSet(k: string, v: string) {
  try { sessionStorage.setItem(k, v); } catch { /* private mode: keep it in memory only */ }
}
