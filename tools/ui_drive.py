"""Run one real task end to end through Ariadne's console, driven in Chrome's debug mode (DevTools protocol).

Everything goes through the page as a person would: type the request on Home, pick the template, start the draft,
fill the form, Sign, then follow the run page (approving asks from the page) until the run ends. Screenshots go to
OUT_DIR on every status or step change and every few minutes; timeline.jsonl records what was seen; findings.json
holds console errors, failed requests and timings. When the run ends, OUT_DIR gets shots of the run and task pages
and, if --open names a file in the workspace, renders of that file at desktop and phone widths.

    python tools/ui_drive.py OUT_DIR --flow coding --name NAME --workspace DIR --text "what you want" [--open index.html]
"""
import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).parent))
from ui_case import CHROME, Page, api  # noqa: E402

PORT = 9334
END = {"done", "needs_you", "failed", "cancelled"}
SHOT_EVERY_S = 300

JS_HELPERS = r"""
window.__set = (el, v) => {
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v);
  el.dispatchEvent(new Event('input', {bubbles: true}));
};
window.__label = (t) => [...document.querySelectorAll('label')].find(l => l.textContent.trim().startsWith(t));
window.__button = (t) => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === t);
"""


async def until(page, js, what, every=1.0):
    t0 = time.time()
    while True:
        v = await page.eval(js)
        if v:
            return v
        if time.time() - t0 > 120:
            raise RuntimeError(f"the page never showed: {what}")
        await asyncio.sleep(every)


async def helpers(page):
    await page.eval(JS_HELPERS)


async def main(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tl = (out / "timeline.jsonl").open("w", encoding="utf-8")
    t_start = time.time()

    def note(kind, **kw):
        rec = {"t": round(time.time() - t_start, 1), "at": time.strftime("%H:%M:%S"), "kind": kind, **kw}
        tl.write(json.dumps(rec) + "\n")
        tl.flush()
        print(json.dumps(rec), flush=True)

    profile = tempfile.mkdtemp(prefix="ariadne-ui-drive-")
    args = [CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--no-first-run",
            "--no-default-browser-check", "--window-size=1440,1000", "about:blank"]
    if a.headless:
        args.insert(1, "--headless=new")
    chrome = subprocess.Popen(args)
    try:
        for _ in range(60):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
                tab = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.5)
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            page = Page(ws)
            pump = asyncio.create_task(page.pump())
            for d in ("Page", "Runtime", "Log", "Network"):
                await page.send(f"{d}.enable")
            await page.size(1440, 1000)
            n = [0]

            async def shot(label):
                n[0] += 1
                p = out / f"{n[0]:02d}-{label}.png"
                await page.shot(p, full=True)
                note("shot", file=p.name)

            # 1. Home: describe the work, pick the template, start a draft
            await page.go(a.base + "/#home", settle=3)
            await helpers(page)
            await until(page, "!!document.querySelector('#ask')", "the start box")
            await page.eval(f"__set(document.querySelector('#ask'), {json.dumps(a.text)})")
            await page.eval(f"""(() => {{ const l = [...document.querySelectorAll('label.flow')]
                 .find(x => x.textContent.trim().startsWith({json.dumps(a.flow)})); l.querySelector('input').click(); }})()""")
            await asyncio.sleep(0.5)
            await shot("home-typed")
            await page.eval("__button('Start a draft').click()")
            hash_ = await until(page, "location.hash.startsWith('#draft/') && location.hash", "the draft page")
            draft_id = hash_.split("/", 1)[1]
            note("draft", id=draft_id)
            await asyncio.sleep(2)
            await helpers(page)
            await shot("draft-opened")

            # 2. The form: name, workspace, goal, run once now; save, then sign
            await until(page, "!!__label('Name')", "the draft form")
            await page.eval(f"__set(__label('Name').querySelector('input'), {json.dumps(a.name)})")
            await page.eval(f"__set(__label('Workspace folder').querySelector('input'), {json.dumps(a.workspace)})")
            if a.goal:
                await page.eval(f"(() => {{ const l = __label('Goal'); if (l) __set(l.querySelector('textarea'), {json.dumps(a.goal)}); }})()")
            await page.eval("document.querySelector('input[name=when][value=now]').click()")
            await asyncio.sleep(0.3)
            await page.eval("__button('Save answers').click()")
            await until(page, "!![...document.querySelectorAll('[role=status]')].find(e => e.textContent.includes('Saved'))"
                              " || !!document.querySelector('form.fill [role=alert]')", "the save result")
            err = await page.eval("document.querySelector('form.fill [role=alert]')?.textContent || ''")
            if err:
                note("form-error", text=err)
            await asyncio.sleep(1)
            await shot("draft-filled")
            ready = await until(page, "(() => { const b = __button('Sign'); return b && !b.disabled; })()", "an enabled Sign")
            note("ready", ready=ready)
            await page.eval("__button('Sign').click()")
            hash_ = await until(page, "(location.hash.startsWith('#run/') || location.hash.startsWith('#task/')) && location.hash",
                                "the run page")
            note("signed", hash=hash_)
            if hash_.startswith("#task/"):
                await shot("task-signed")
                rid = await until(page, "document.querySelector('a[href^=\"#run/\"]')?.getAttribute('href')", "a run link")
                await page.go(a.base + "/" + rid, settle=2)
                hash_ = rid
            run_id = hash_.split("/", 1)[1]
            await asyncio.sleep(2)
            await shot("run-started")

            # 3. Follow the run from its page until it ends
            last, last_shot = None, time.time()
            while True:
                r = next((x for x in api(a.base, "runs", limit=60) if x["id"] == run_id), None)
                if r is None:
                    await asyncio.sleep(10)
                    continue
                key = (r["status"], r.get("step"))
                if key != last:
                    note("status", status=r["status"], step=r.get("step"), steps=r.get("steps_total"),
                         ask=(r.get("ask") or {}).get("what"))
                    await helpers(page)
                    await shot(f"run-{r['status']}-step{r.get('step')}")
                    last, last_shot = key, time.time()
                    if r["status"] == "asking":
                        await asyncio.sleep(1)
                        await page.eval("__button('Approve for this run')?.click()")
                        note("approved-from-page", what=(r.get("ask") or {}).get("what"))
                elif time.time() - last_shot > SHOT_EVERY_S:
                    await shot(f"run-{r['status']}-step{r.get('step')}-t{int(time.time() - t_start)}")
                    last_shot = time.time()
                if r["status"] in END:
                    break
                await asyncio.sleep(15)

            # 4. The end: run and task pages, then what it made
            await page.go(a.base + f"/#run/{run_id}", settle=3)
            await shot("run-final")
            await page.eval("[...document.querySelectorAll('button,a')].find(e => e.textContent.startsWith('Show the activity'))?.click()")
            await asyncio.sleep(1)
            await shot("run-final-activity")
            tid = next((t["id"] for t in api(a.base, "tasks") if t["name"] == a.name), None)
            if tid:
                await page.go(a.base + f"/#task/{tid}", settle=3)
                await shot("task-final")
            if a.open:
                f = Path(a.workspace) / a.open
                if f.exists():
                    await page.go(f.resolve().as_uri(), settle=3)
                    await shot("made-desktop")
                    await page.size(390, 844, mobile=True)
                    await page.go(f.resolve().as_uri(), settle=3)
                    await shot("made-phone")
                    await page.size(1440, 1000)
                else:
                    note("missing", file=str(f))
            pump.cancel()
            (out / "findings.json").write_text(json.dumps({
                "draft": draft_id, "run": run_id, "status": r["status"], "minutes": round((time.time() - t_start) / 60, 1),
                "console": page.log}, indent=2), encoding="utf-8")
            note("end", status=r["status"])
    finally:
        tl.close()
        chrome.terminate()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("out")
    p.add_argument("--base", default="http://127.0.0.1:8917")
    p.add_argument("--flow", default="coding")
    p.add_argument("--name", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--goal", default="")
    p.add_argument("--open", default="")
    p.add_argument("--headless", action="store_true")
    asyncio.run(main(p.parse_args()))
