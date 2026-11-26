"""Screenshot console pages in Chrome's debug mode: `python tools/ui_shot.py OUT_DIR URL_OR_HASH... [--base URL]`.

Each argument is a full URL or a hash route ('#run/<id>', '#task/<id>'); one PNG per page, full height, 1440 wide.
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).parent))
from ui_case import CHROME, Page  # noqa: E402

PORT = 9335


async def main(out, pages, base):
    out.mkdir(parents=True, exist_ok=True)
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                               f"--user-data-dir={tempfile.mkdtemp(prefix='ariadne-shot-')}", "about:blank"])
    try:
        for _ in range(60):
            try:
                tab = next(t for t in json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
                           if t["type"] == "page")
                break
            except Exception:
                await asyncio.sleep(0.5)
        async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            page = Page(ws)
            pump = asyncio.create_task(page.pump())
            await page.send("Page.enable")
            await page.size(1440, 1000)
            for i, p in enumerate(pages, 1):
                url = p if "://" in p else f"{base}/{p}"
                await page.go(url, settle=3)
                name = out / f"{i:02d}-{p.strip('#').replace('/', '-')[:40] or 'home'}.png"
                await page.shot(name)
                print(name)
            pump.cancel()
    finally:
        chrome.terminate()


if __name__ == "__main__":
    a = sys.argv[1:]
    base = a[a.index("--base") + 1] if "--base" in a else "http://127.0.0.1:8917"
    a = [x for i, x in enumerate(a) if x != "--base" and (i == 0 or a[i - 1] != "--base")]
    asyncio.run(main(Path(a[0]), a[1:], base))
