"""Gate: the sources ledger is complete, attributed and recent (docs/WORKER-RECIPE.md, W6, W7).

    python {checks}/sources_ledger.py SOURCES.md [--min 3] [--within-days N] [--today YYYY-MM-DD]

Each source is one line:   - <url> | <publisher> | <what it supports> | <YYYY-MM-DD>
Checked: at least --min distinct URLs; every line with a URL follows that format and has a date; the publisher
matches the URL's site (a word of the publisher appears in the host, or a word of the host appears in the
publisher, ignoring case and punctuation: "Reuters" matches reuters.com, "SEC EDGAR" matches sec.gov); no date is
after today; with --within-days, every date is inside that window. Prints each problem and exits 1, or a one-line
pass and exits 0. Never raises.
"""
import datetime as dt
import re
import sys
from urllib.parse import urlparse

LINE = re.compile(r"^\s*[-*]\s*(?P<url>https?://\S+?)\s*\|\s*(?P<pub>[^|]+?)\s*\|\s*(?P<what>[^|]*?)\s*\|\s*"
                  r"(?P<date>\d{4}-\d{2}-\d{2})\s*$")
URL = re.compile(r"https?://[^\s)|>\]]+")
GENERIC = {"www", "com", "org", "net", "gov", "co", "uk", "io", "the", "news", "inc", "and", "of", "ir", "investor",
           "investors", "edu", "html", "amp"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def attributed(url, pub):
    host = urlparse(url).netloc.lower().split(":")[0]
    host_words = [p for p in re.split(r"[.\-]", host) if len(p) >= 3 and p not in GENERIC]
    pub_words = [norm(w) for w in re.split(r"[\s/,()&.\-]+", pub) if len(norm(w)) >= 3 and norm(w) not in GENERIC]
    p = norm(pub)
    return any(w in norm(host) for w in pub_words) or any(w in p for w in host_words)


def main(argv):
    path = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))), None)
    opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
    if not path:
        print("usage: sources_ledger.py SOURCES.md [--min 3] [--within-days N] [--today YYYY-MM-DD]")
        return 2
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
        today = dt.date.fromisoformat(opt["--today"]) if "--today" in opt else dt.date.today()
        window = int(opt["--within-days"]) if "--within-days" in opt else None
        need = int(opt.get("--min", 3))
    except (OSError, ValueError) as e:
        print(f"cannot check {path}: {e}")
        return 1
    problems, urls = [], set()
    for n, line in enumerate(lines, 1):
        if not URL.search(line):
            continue
        m = LINE.match(line)
        if not m:
            problems.append(f"line {n}: write it as '- <url> | <publisher> | <what it supports> | <YYYY-MM-DD>'")
            continue
        url, pub, date = m["url"], m["pub"], m["date"]
        urls.add(url.rstrip("/"))
        if not attributed(url, pub):
            problems.append(f"line {n}: publisher '{pub}' does not match the site {urlparse(url).netloc}")
        try:
            d = dt.date.fromisoformat(date)
        except ValueError:
            problems.append(f"line {n}: '{date}' is not a date")
            continue
        if d > today:
            problems.append(f"line {n}: dated {date}, after today ({today})")
        elif window is not None and (today - d).days > window:
            problems.append(f"line {n}: dated {date}, older than {window} days before {today}")
    if len(urls) < need:
        problems.append(f"{len(urls)} distinct source(s); at least {need} needed")
    if problems:
        print(f"{path}:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"ok: {len(urls)} sources, each attributed and dated" + (f" within {window} days" if window else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
