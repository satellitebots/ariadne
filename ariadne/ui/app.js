// Ariadne's console: sessions are the only navigation; the centre renders present.view(); the verbs are the ones
// the task legalises. No framework, no bundler - one module the server hands to the browser.

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
};

const state = { choices: null, sessions: [], session: null, task: null, since: 0, replyKind: "", timer: 0 };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}

function fail(e) {
  const box = $("#error");
  box.textContent = String(e.message || e);
  box.hidden = false;
  setTimeout(() => { box.hidden = true; }, 8000);
}

// ---------- data ----------
async function loadChoices() {
  state.choices = await api("/api/choices");
  const flow = $("#nt-flow"), model = $("#nt-model");
  for (const f of state.choices.flows) {
    const o = el("option", "", `${f.name} - ${f.when}`);
    o.value = f.name;
    flow.append(o);
  }
  for (const m of state.choices.models) {
    const o = el("option", "", `${m.name}${m.installed ? "" : " (not installed)"}`);
    o.value = m.name;
    model.append(o);
  }
  flow.addEventListener("change", gateSubmit);
  model.addEventListener("change", gateSubmit);
  gateSubmit();
}

function gateSubmit() {
  const ok = $("#nt-flow").value && $("#nt-model").value && $("#nt-text").value.trim();
  $("#nt-submit").disabled = !ok;
}

async function loadInbox() {
  const box = await api("/api/inbox");
  $("#worker").textContent = `worker: ${box.worker ? "running" : "not running"}`;
  const needs = $("#needs");
  needs.replaceChildren();
  if (!box.waiting.length) {
    needs.append(el("span", "muted small", "Nothing needs you."));
    return;
  }
  for (const t of box.waiting) needs.append(needChip(t));
}

function needChip(t) {
  const b = el("button", "chip");
  b.append(el("span", "id", t.id));
  b.append(document.createTextNode(`${t.label} · ${firstLine(t.brief)}`));
  b.addEventListener("click", () => openTask(t.id, t.session));
  return b;
}

const firstLine = (text) => String(text || "").split("\n")[0].slice(0, 70);

async function loadSessions() {
  state.sessions = await api("/api/sessions");
  const list = $("#session-list");
  list.replaceChildren();
  $("#sessions-empty").hidden = state.sessions.length > 0;
  for (const s of state.sessions) {
    const li = el("li");
    if (state.session === s.name) li.classList.add("active");
    const row = el("div", "name");
    row.append(el("span", "", s.name));
    if (s.waiting) row.append(el("span", "wait", `${s.waiting} waiting`));
    li.append(row);
    li.append(el("div", "flow", `${s.flow || "no flow yet"} · segment ${s.segment}`));
    li.addEventListener("click", () => openSession(s.name));
    list.append(li);
  }
}

async function openSession(name) {
  state.session = name;
  state.task = null;
  await loadSessions();
  const s = state.sessions.find((x) => x.name === name);
  $("#session-title").textContent = name;
  $("#session-meta").textContent = s ? `${s.flow || "no flow"} · ${s.tasks.length} task(s)` : "";
  renderTimeline(s);
  renderTask(null);
}

function renderTimeline(s) {
  const ol = $("#timeline");
  ol.replaceChildren();
  if (!s) return;
  for (const t of s.tasks) {
    const li = el("li");
    li.append(el("span", "", `${t.id.split("-").pop()} · ${firstLine(t.text?.[0] || "")}`));
    li.append(el("span", "st", t.label));
    li.addEventListener("click", () => openTask(t.id, s.name));
    ol.append(li);
  }
  if (!s.tasks.length) ol.append(el("li", "muted", "No tasks in this session yet."));
}

async function openTask(id, session) {
  try {
    const doc = await api(`/api/tasks/${encodeURIComponent(id)}`);
    state.task = doc;
    if (session && session !== state.session) await openSession(session);
    if (session) {
      const s = state.sessions.find((x) => x.name === session);
      renderTimeline(s);
      for (const li of document.querySelectorAll("#timeline li")) {
        if (li.textContent.startsWith(id.split("-").pop())) li.classList.add("active");
      }
    }
    renderTask(doc);
  } catch (e) {
    fail(e);
  }
}

// ---------- rendering ----------
function renderTask(doc) {
  const box = $("#task");
  box.replaceChildren();
  const actions = $("#actions"), gateEditor = $("#gate-editor"), reply = $("#reply-editor");
  actions.replaceChildren();
  gateEditor.hidden = true;
  reply.hidden = true;
  $("#fetch-note").textContent = "";
  if (!doc) {
    box.append(el("p", "muted", "Nothing is opened for you. Click a session, then a task in its timeline."));
    actions.append(el("p", "muted small", "The verbs legal for the selected task appear here."));
    return;
  }

  const head = el("div");
  head.append(el("h3", "", firstLine(doc.brief) || doc.id));
  const meta = el("div", "meta");
  meta.append(el("span", "badge " + doc.status, doc.label));
  meta.append(document.createTextNode(`  ${doc.id}`));
  if (doc.flow) meta.append(document.createTextNode(`  ·  ${doc.flow}`));
  if (doc.model) meta.append(document.createTextNode(`  ·  ${doc.model}`));
  if (doc.session) meta.append(document.createTextNode(`  ·  ${doc.session}`));
  if (doc.workspace) meta.append(document.createTextNode(`  ·  ${doc.workspace}`));
  head.append(meta);
  box.append(head);

  box.append(section("Brief", el("p", "", doc.brief)));

  if (doc.gates && doc.gates.length) {
    const ul = el("ul");
    for (const g of doc.gates) ul.append(el("li", "", `[${g.type}] ${g.text}`));
    box.append(section("Check gates", ul));
  }

  const s = doc.sections || {};
  if (s.mission || (s.steps && s.steps.length)) {
    const wrap = el("div");
    if (s.mission) wrap.append(el("p", "", s.mission));
    const ol = el("ol");
    for (const step of s.steps || []) {
      const li = el("li");
      li.append(document.createTextNode(step.text));
      if (step.model) li.append(el("span", "step-model", step.model));
      ol.append(li);
    }
    wrap.append(ol);
    box.append(section("Backbrief", wrap));
    if (s.checks && s.checks.length) {
      const ul = el("ul");
      for (const c of s.checks) ul.append(el("li", "", c));
      box.append(section("How the plan proves each gate", ul));
    }
    if (s.risks && s.risks.length) {
      const ul = el("ul");
      for (const r of s.risks) ul.append(el("li", "", r));
      box.append(section("Risks", ul));
    }
    if (s.questions && s.questions.length) {
      const ul = el("ul");
      for (const q of s.questions) ul.append(el("li", "", q));
      box.append(section("Questions", ul));
    }
  } else if (doc.document) {
    box.append(section("Backbrief", el("pre", "", doc.document)));
  }

  if (doc.report) box.append(section(doc.status === "done" ? "Report" : "Result", el("pre", "", doc.report)));
  if (doc.error) box.append(section("Stopped", el("pre", "", doc.error)));
  if (doc.events && doc.events.length) {
    const ul = el("ul");
    for (const e of doc.events.slice(-8)) ul.append(el("li", "small muted", e));
    box.append(section("Activity", ul));
  }

  renderActions(doc, actions, gateEditor, reply);
}

function bubble(text, who) {
  const log = $("#chat-log");
  log.append(el("div", `bubble ${who}`, text));
  log.scrollTop = log.scrollHeight;
}

function section(title, body) {
  const s = el("section");
  s.append(el("h4", "", title));
  s.append(body);
  return s;
}

function renderActions(doc, box, gateEditor, reply) {
  const verbs = doc.actions || [];
  if (!verbs.length) {
    box.append(el("p", "muted small", doc.next || "No verbs are legal for this status."));
    return;
  }
  for (const verb of verbs) {
    const b = el("button", "btn" + (verb === "approve" ? " primary" : verb === "cancel" ? " danger" : ""), verb);
    b.addEventListener("click", () => doVerb(verb, doc, gateEditor, reply));
    box.append(b);
  }
  if (doc.next) box.append(el("p", "muted small", doc.next));
}

async function doVerb(verb, doc, gateEditor, reply) {
  try {
    if (verb === "cancel") {
      if (!confirm(`Cancel ${doc.id}?`)) return;
      state.task = await api(`/api/tasks/${doc.id}/cancel`, { method: "POST" });
    } else if (verb === "approve") {
      const models = prompt("Change a step's model before locking the plan? (e.g. 2=gemma-4-12b, all=qwen3.6-35b-a3b)", "");
      if (models === null) return;
      state.task = await api(`/api/tasks/${doc.id}/approve`,
        { method: "POST", body: JSON.stringify({ models: (models || "").replace(/\s+/g, "") }) });
    } else if (verb === "revise") {
      state.replyKind = "revise";
      $("#reply-label").firstChild.textContent = "What should change in the plan? ";
      $("#reply-text").placeholder = "the feedback the planner must address";
      reply.hidden = false;
      $("#reply-text").focus();
      return;
    } else if (verb === "set_gates") {
      $("#gates-text").value = (doc.gates || []).map((g) => (g.type === "run" ? "run: " : "") + g.text).join("\n");
      gateEditor.hidden = false;
      $("#gates-text").focus();
      return;
    }
    await refresh(doc.id);
  } catch (e) {
    fail(e);
  }
}

async function refresh(id) {
  await loadInbox();
  await loadSessions();
  if (state.session) renderTimeline(state.sessions.find((s) => s.name === state.session));
  if (id) state.task = await api(`/api/tasks/${encodeURIComponent(id)}`);
  renderTask(state.task);
}

// ---------- wiring ----------
function wire() {
  $("#toggle-new").addEventListener("click", () => {
    const form = $("#new-task");
    form.hidden = !form.hidden;
    if (!form.hidden) $("#nt-text").focus();
  });
  for (const id of ["#nt-text"]) $(id).addEventListener("input", gateSubmit);
  $("#nt-submit").addEventListener("click", async () => {
    try {
      const gates = $("#nt-gates").value.split("\n").map((g) => g.trim()).filter(Boolean);
      const doc = await api("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          text: $("#nt-text").value, flow: $("#nt-flow").value, model: $("#nt-model").value,
          workspace: $("#nt-workspace").value.trim(), session: $("#nt-session").value.trim(), gates,
        }),
      });
      $("#nt-text").value = "";
      $("#nt-gates").value = "";
      openTask(doc.id, doc.session);
    } catch (e) {
      fail(e);
    }
  });
  $("#save-gates").addEventListener("click", async () => {
    try {
      const gates = $("#gates-text").value.split("\n").map((g) => g.trim()).filter(Boolean);
      state.task = await api(`/api/tasks/${state.task.id}/gates`,
        { method: "POST", body: JSON.stringify({ gates }) });
      await refresh(state.task.id);
    } catch (e) {
      fail(e);
    }
  });
  $("#send-reply").addEventListener("click", async () => {
    try {
      const text = $("#reply-text").value.trim();
      if (!text) return;
      if (state.replyKind === "revise") {
        state.task = await api(`/api/tasks/${state.task.id}/revise`,
          { method: "POST", body: JSON.stringify({ feedback: text }) });
      } else {
        await api(`/api/tasks/${state.task.id}/feedback`,
          { method: "POST", body: JSON.stringify({ feedback: text }) });
      }
      $("#reply-text").value = "";
      $("#reply-editor").hidden = true;
      await refresh(state.task.id);
    } catch (e) {
      fail(e);
    }
  });

  $("#chat-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const box = $("#chat-text"), send = $("#chat-send");
    const message = box.value.trim();
    if (!message) return;
    bubble(message, "you");
    box.value = "";
    send.disabled = true;
    send.textContent = "Thinking…";
    try {
      const out = await api("/api/chat", { method: "POST", body: JSON.stringify({ message, session: state.session || "" }) });
      bubble(out.reply, "it");
    } catch (err) {
      bubble(String(err.message || err), "it");
    } finally {
      send.disabled = false;
      send.textContent = "Send";
    }
  });

  const es = new EventSource(`/api/events?since=${state.since}`);
  es.onmessage = (m) => {
    try {
      const ev = JSON.parse(m.data);
      state.since = Math.max(state.since, Number(ev.ts) || 0);
      clearTimeout(state.timer);
      state.timer = setTimeout(() => {
        if (state.task && ev.task_id === state.task.id) refresh(state.task.id).catch(fail);
        else { loadInbox().catch(fail); loadSessions().catch(fail); }
      }, 400);
    } catch { /* keepalive or partial frame */ }
  };
  es.onerror = () => { /* EventSource reconnects with the same `since`; nothing to do */ };
}

(async function boot() {
  try {
    await loadChoices();
    await loadInbox();
    await loadSessions();
    wire();
    renderTask(null);
  } catch (e) {
    fail(e);
  }
})();
