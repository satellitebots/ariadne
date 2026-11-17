"""Egress hook for every Python process in Ariadne's .venv (CLI, auto-started gateway, Python children).

Loaded at interpreter start by .venv\\Lib\\site-packages\\ariadne_egress.pth (installed by
tools\\install-egress-hook.ps1). Does nothing unless ARIADNE_EGRESS_LOG is set.

Logs one JSON line per event to ARIADNE_EGRESS_LOG:
  dns      socket.getaddrinfo(host, port)   - every name lookup (covers asyncio, httpx, requests, urllib)
  connect  socket.connect / connect_ex      - sync connects to an address
  spawn    subprocess.Popen(args)           - child processes (git, npx, uvx ...) that may reach the network
Fields: t, pid, kind, host, port, where (last 6 Hermes frames; stdlib, site-packages, this file filtered).
Limitation: asyncio's Windows proactor connects without socket.connect; its name lookups still pass
through getaddrinfo, so hosts reached by name are logged, raw-IP asyncio connects would be missed.
"""
import os

LOG = os.environ.get("ARIADNE_EGRESS_LOG")
if LOG:
    import json, socket, subprocess, threading, time, traceback

    _lock = threading.Lock()
    _pid = os.getpid()

    def _where():
        frames = [f for f in traceback.extract_stack()[:-2]
                  if "site-packages" not in f.filename and "egress_hook" not in f.filename
                  and "\\Lib\\" not in f.filename and "/lib/python" not in f.filename]
        return [f"{f.filename.split('upstream')[-1].lstrip(chr(92) + '/')}:{f.lineno}" for f in frames[-6:]]

    def _rec(kind, host, port):
        line = json.dumps({"t": round(time.time(), 3), "pid": _pid, "kind": kind,
                           "host": str(host)[:300], "port": port, "where": _where()})
        with _lock, open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    _getaddrinfo = socket.getaddrinfo
    def _ga(host, port, *a, **k):
        _rec("dns", host, port)
        return _getaddrinfo(host, port, *a, **k)
    socket.getaddrinfo = _ga

    _connect, _connect_ex = socket.socket.connect, socket.socket.connect_ex
    def _c(self, addr):
        if isinstance(addr, tuple):
            _rec("connect", addr[0], addr[1])
        return _connect(self, addr)
    def _cx(self, addr):
        if isinstance(addr, tuple):
            _rec("connect", addr[0], addr[1])
        return _connect_ex(self, addr)
    socket.socket.connect, socket.socket.connect_ex = _c, _cx

    _popen_init = subprocess.Popen.__init__
    def _p(self, args, *a, **k):
        _rec("spawn", args if isinstance(args, str) else " ".join(map(str, args)), None)
        return _popen_init(self, args, *a, **k)
    subprocess.Popen.__init__ = _p
