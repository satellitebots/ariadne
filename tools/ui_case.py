"""Drive Ariadne's UI in Chrome's debug mode (DevTools protocol) for the UI case study.

Launches Chrome with its own throwaway profile and --remote-debugging-port, visits each view of `ariadne ui`, takes
screenshots at desktop and phone widths and in dark mode, and records every console message, page error and failed
or 4xx/5xx request. Writes the screenshots and findings.json to the output folder.

    python tools/ui_case.py OUT_DIR [--base http://127.0.0.1:8917]
"""
import asyncio
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.waiting, self.log = ws, 0, {}, []

    async def pump(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.waiting:
                self.waiting.pop(m["id"]).set_result(m)
                continue
            meth, p = m.get("method", ""), m.get("params", {})
            if meth == "Runtime.consoleAPICalled":
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))
                self.log.append({"kind": f"console.{p.get('type')}", "text": text[:500]})
            elif meth == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                self.log.append({"kind": "exception", "text": (d.get("exception", {}).get("description")
                                                               or d.get("text", ""))[:800]})
            elif meth == "Log.entryAdded":
                e = p.get("entry", {})
                if e.get("level") in ("error", "warning"):
                    self.log.append({"kind": f"log.{e['level']}", "text": f"{e.get('text', '')} {e.get('url', '')}"[:500]})
            elif meth == "Network.responseReceived":
                r = p.get("response", {})
                if r.get("status", 200) >= 400:
                    self.log.append({"kind": "http", "text": f"{r['status']} {r.get('url')}"})
            elif meth == "Network.loadingFailed":
                if not p.get("canceled"):
                    self.log.append({"kind": "net-failed", "text": f"{p.get('errorText')} {p.get('type')}"})

    async def send(self, method, **params):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.waiting[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        m = await asyncio.wait_for(fut, 60)
        if "error" in m:
            raise RuntimeError(f"{method}: {m['error']}")
        return m.get("result", {})

    async def eval(self, js):
        r = await self.send("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def size(self, w, h, mobile=False):
        await self.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)

    async def dark(self, on):
        await self.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme",
                                                                 "value": "dark" if on else "light"}])

    async def go(self, url, settle=2.5):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(settle)

    async def shot(self, path, full=True):
        r = await self.send("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        Path(path).write_bytes(base64.b64decode(r["data"]))


def api(base, verb, **args):
    req = urllib.request.Request(f"{base}/api/v/{verb}", data=json.dumps(args).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


async def main(out, base):
    out.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="ariadne-ui-case-")
    chrome = subprocess.Popen([CHROME, f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
                               "--headless=new", "--no-first-run", "--no-default-browser-check",
                               "--window-size=1440,900", "about:blank"])
    try:
        for _ in range(50):
            try:
                tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=2).read())
                target = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.3)
        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            pg = Page(ws)
            pump = asyncio.create_task(pg.pump())
            for d in ("Page", "Runtime", "Log", "Network"):
                await pg.send(f"{d}.enable")
            runs = api(base, "runs", limit=200)
            live = next((r for r in runs if r["status"] in ("running", "waiting", "parked")), None)
            asking = next((r for r in runs if r["status"] == "asking"), None)
            run = live or (runs[0] if runs else None)
            done = next((r for r in runs if r["status"] in ("done", "needs_you")), None)
            tasks = api(base, "tasks")
            drafts = api(base, "drafts")
            scenes = [("home", "#"), ("runs", "#runs"), ("machine", "#machine"), ("templates", "#templates"),
                      ("rules", "#rules"), ("task", f"#task/{tasks[0]['id']}" if tasks else "#")]
            if run:
                scenes.append(("run-live" if live else "run", f"#run/{run['id']}"))
            if asking:
                scenes.append(("run-asking", f"#run/{asking['id']}"))
            if done:
                scenes.append((f"run-{done['status']}", f"#run/{done['id']}"))
            if drafts:
                scenes.append(("draft", f"#draft/{drafts[0]['id']}"))
            found, timings = {}, {}
            for dark in (False, True):
                await pg.dark(dark)
                for label, w, h, mob in (("desktop", 1440, 900, False), ("phone", 390, 844, True)):
                    if dark and label == "phone":
                        continue
                    await pg.size(w, h, mob)
                    for name, frag in scenes:
                        pg.log = []
                        t0 = time.time()
                        await pg.go(f"{base}/{frag}")
                        timings[f"{name}-{label}"] = round(time.time() - t0, 2)
                        tag = f"{name}-{label}{'-dark' if dark else ''}"
                        await pg.shot(out / f"{tag}.png")
                        probe = await pg.eval("""(() => ({
                            title: document.title,
                            h1: [...document.querySelectorAll('h1')].map(e => e.innerText).slice(0, 3),
                            overflowX: document.documentElement.scrollWidth > window.innerWidth + 1,
                            now: (document.querySelector('.now') || {}).innerText || '',
                            unlabeled: [...document.querySelectorAll('button, input, textarea, select')]
                              .filter(e => !(e.innerText || e.getAttribute('aria-label') || e.labels?.length
                                             || e.getAttribute('placeholder') || e.title)).length,
                            smallText: [...document.querySelectorAll('body *')].filter(e => e.childNodes.length
                              && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())
                              && parseFloat(getComputedStyle(e).fontSize) < 12).length,
                          }))()""")
                        found[tag] = {"url": frag, "probe": probe, "log": pg.log}
            # the activity log of a run: open it and screenshot the newest events
            if run:
                await pg.dark(False)
                await pg.size(1440, 900)
                await pg.go(f"{base}/#run/{run['id']}")
                await pg.eval("[...document.querySelectorAll('button')].find(b => /activity/i.test(b.innerText))?.click()")
                await asyncio.sleep(1)
                await pg.shot(out / "run-activity-desktop.png")
                found["run-activity"] = {"probe": await pg.eval(
                    "[...document.querySelectorAll('.events li, .activity li, li')].slice(-8).map(e => e.innerText.slice(0, 160))")}
            pump.cancel()
        (out / "findings.json").write_text(json.dumps({"base": base, "scenes": found}, indent=1), encoding="utf-8")
        print(json.dumps({k: {"h1": v.get("probe", {}).get("h1") if isinstance(v.get("probe"), dict) else None,
                              "overflowX": v.get("probe", {}).get("overflowX") if isinstance(v.get("probe"), dict) else None,
                              "issues": len(v.get("log", []))} for k, v in found.items()}, indent=1))
    finally:
        chrome.terminate()


if __name__ == "__main__":
    args = sys.argv[1:]
    base = args[args.index("--base") + 1] if "--base" in args else "http://127.0.0.1:8917"
    asyncio.run(main(Path(args[0]), base))
