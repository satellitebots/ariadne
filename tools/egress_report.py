"""Summarise an egress_hook JSONL log. Exit 1 if any attempt targets a non-local host.

Usage: python tools\\egress_report.py <log.jsonl>
Local = localhost, loopback, private LAN ranges (RFC 1918), link-local, unspecified.
Spawned processes are listed; a spawn is flagged 'net?' when its command looks networked
(git fetch/pull/ls-remote/clone, curl, wget, pip, npm, npx, uvx, an http(s) URL).
"""
import collections, ipaddress, json, re, sys

NET_CMD = re.compile(r"\b(fetch|pull|ls-remote|clone|curl|wget|pip|npm|npx|uvx)\b|https?://", re.I)


def is_local(host):
    h = (host or "").strip().strip("[]").lower()
    if h in ("", "none", "localhost") or h.endswith(".localhost") or h.endswith(".lan"):
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
        return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
    except ValueError:
        return False  # a public DNS name: looking it up is already an egress attempt


rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
net = collections.OrderedDict()
spawns = collections.OrderedDict()
for r in rows:
    if r["kind"] in ("dns", "connect"):
        key = (r["host"], r["port"])
        e = net.setdefault(key, {"n": 0, "kinds": set(), "where": r["where"]})
        e["n"] += 1
        e["kinds"].add(r["kind"])
    elif r["kind"] == "spawn":
        e = spawns.setdefault(r["host"][:160], {"n": 0, "where": r["where"]})
        e["n"] += 1

external = [(k, v) for k, v in net.items() if not is_local(k[0])]
print(f"events={len(rows)} endpoints={len(net)} external={len(external)} spawns={len(spawns)}")
print("\nENDPOINTS (host:port  count  kinds  local?  where)")
for (host, port), v in net.items():
    print(f"  {host}:{port}  x{v['n']}  {','.join(sorted(v['kinds']))}  "
          f"{'local' if is_local(host) else 'EXTERNAL'}  {' <- '.join(reversed(v['where']))}")
print("\nSPAWNS (command  count  net?  where)")
for cmd, v in spawns.items():
    print(f"  {cmd}  x{v['n']}  {'net?' if NET_CMD.search(cmd) else '-'}  {' <- '.join(reversed(v['where']))}")
sys.exit(1 if external else 0)
