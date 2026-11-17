"""Process-wide network guard: refuse any connection to a host outside the machine or the LAN.

Wraps socket.getaddrinfo, socket.socket.connect/connect_ex and the asyncio event-loop sock_connect
methods. A refused attempt raises PermissionError (an OSError, so HTTP clients treat it as an ordinary
network failure) and is appended to the guard log with the calling frames.

Modes (env ARIADNE_OFFLINE_GUARD): enforce (default) | log (allow but record) | off.
Extra allowed hosts (env ARIADNE_ALLOW_HOSTS): comma-separated names or IPs, e.g. "gpu-box.corp,10.9.0.4".
"""
import asyncio.base_events
import ipaddress
import json
import os
import socket
import threading
import time
import traceback

_LOCAL_SUFFIXES = (".localhost", ".lan", ".local", ".home.arpa", ".internal")
_lock = threading.Lock()
_installed = False
_state = {"mode": "enforce", "log": None, "allow": set(), "blocked": 0}


def is_local_host(host) -> bool:
    """True for loopback, private (RFC 1918 / ULA), link-local, unspecified, single-label LAN names,
    local suffixes, and anything in ARIADNE_ALLOW_HOSTS. Public names and IPs are not local."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    h = str(host).strip().strip("[]").rstrip(".").lower()
    if h in ("", "localhost") or h in _state["allow"]:
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
        return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
    except ValueError:
        pass
    if "." not in h:  # single-label name: only resolvable on the LAN
        return True
    return h.endswith(_LOCAL_SUFFIXES)


def _frames():
    out = []
    for f in traceback.extract_stack()[:-3]:
        if "offline_guard" in f.filename or "egress_hook" in f.filename:
            continue
        out.append(f"{os.path.basename(f.filename)}:{f.lineno}")
    return out[-6:]


def _check(kind, host, port):
    if is_local_host(host):
        return
    mode = _state["mode"]
    entry = {"t": round(time.time(), 3), "pid": os.getpid(), "kind": kind, "host": str(host)[:200],
             "port": port, "mode": mode, "where": _frames()}
    with _lock:
        _state["blocked"] += 1
        if _state["log"]:
            try:
                with open(_state["log"], "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError:
                pass
    if mode == "enforce":
        raise PermissionError(f"Ariadne offline guard: blocked {kind} to {host}:{port} (not a local host)")


def _addr_host(addr):
    return addr[0] if isinstance(addr, tuple) and addr else None


def install(log_path=None, mode=None, allow=None):
    """Install the guard once per process. Safe to call again (updates mode/log/allow only)."""
    global _installed
    _state["mode"] = (mode or os.environ.get("ARIADNE_OFFLINE_GUARD") or "enforce").strip().lower()
    _state["log"] = log_path
    extra = allow if allow is not None else os.environ.get("ARIADNE_ALLOW_HOSTS", "").split(",")
    _state["allow"] = {a.strip().lower() for a in extra if a and a.strip()}
    if _state["mode"] == "off" or _installed:
        return _state["mode"]
    # One guard per process: the .pth loader (tools\install-guard-pth.ps1) and the Hermes plugin load this file
    # as two different modules; the marker on the socket module stops the second from wrapping again.
    if getattr(socket, "_ariadne_offline_guard", False):
        _installed = True
        return _state["mode"]

    orig_gai = socket.getaddrinfo
    def getaddrinfo(host, port, *a, **k):
        _check("dns", host, port)
        return orig_gai(host, port, *a, **k)
    socket.getaddrinfo = getaddrinfo

    orig_connect, orig_connect_ex = socket.socket.connect, socket.socket.connect_ex
    def connect(self, address):
        _check("connect", _addr_host(address), address[1] if isinstance(address, tuple) and len(address) > 1 else None)
        return orig_connect(self, address)
    def connect_ex(self, address):
        _check("connect", _addr_host(address), address[1] if isinstance(address, tuple) and len(address) > 1 else None)
        return orig_connect_ex(self, address)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex

    # asyncio connects raw IPs without socket.connect (Windows proactor: ConnectEx), so wrap sock_connect
    # on every loop class that defines it.
    import asyncio.proactor_events, asyncio.selector_events  # noqa: E401
    for cls in (asyncio.base_events.BaseEventLoop, asyncio.proactor_events.BaseProactorEventLoop,
                asyncio.selector_events.BaseSelectorEventLoop):
        orig = cls.__dict__.get("sock_connect")
        if orig is None:
            continue
        def make(o):
            async def sock_connect(self, sock, address):
                _check("connect", _addr_host(address), address[1] if isinstance(address, tuple) and len(address) > 1 else None)
                return await o(self, sock, address)
            return sock_connect
        cls.sock_connect = make(orig)
    socket._ariadne_offline_guard = True
    _installed = True
    return _state["mode"]


def blocked_count():
    return _state["blocked"]
