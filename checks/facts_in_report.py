"""Gate: every fact in a facts file appears in the report exactly as recorded (docs/WORKER-RECIPE.md, W2).

    python {checks}/facts_in_report.py REPORT.md data/facts.json [--keys a,b.c] [--decimals 2]

The facts file is JSON. Any shape works: every number found in it (nested objects and lists included) is a fact,
named by its path (change_3m.pct, items.0.value). A fact counts as shown when the report contains it written with
the given decimals (sign ignored, thousands separators allowed), or exactly as stored. --keys limits the check to
those paths (prefixes match: change_3m covers change_3m.pct). Booleans and the keys from, to, date, as_of, year,
rows, n and count are not numbers to show.

Prints what is missing and exits 1; prints a one-line pass and exits 0. Never raises.
"""
import json
import re
import sys

SKIP = {"from", "to", "date", "as_of", "year", "rows", "n", "count"}


def walk(obj, path=""):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) not in SKIP:
                yield from walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}.{i}" if path else str(i))


def shown(value, text, decimals):
    plain = text.replace(",", "")
    forms = {format(abs(float(value)), f".{decimals}f"), str(abs(value))}
    if float(value).is_integer():
        forms.add(str(int(abs(value))))
    return any(re.search(r"(?<![\d.])" + re.escape(f) + r"(?![\d])", plain) for f in forms)


def options(argv, names):
    opt, rest, skip = {}, [], False
    for i, a in enumerate(argv):
        if skip:
            skip = False
            continue
        if a in names and i + 1 < len(argv):
            opt[a], skip = argv[i + 1], True
        elif a.startswith("--"):
            opt[a] = True
        else:
            rest.append(a)
    return opt, rest


def main(argv):
    opt, args = options(argv, ("--keys", "--decimals"))
    if len(args) < 2:
        print("usage: facts_in_report.py REPORT.md FACTS.json [--keys a,b] [--decimals 2]")
        return 2
    try:
        text = open(args[0], encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read the report {args[0]}: {e}")
        return 1
    try:
        facts = json.load(open(args[1], encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"cannot read the facts file {args[1]}: {e}")
        return 1
    decimals = int(opt.get("--decimals") or 2)
    keys = [k for k in str(opt.get("--keys") or "").split(",") if k]
    items = [(p, v) for p, v in walk(facts) if not keys or any(p == k or p.startswith(k + ".") for k in keys)]
    if keys:
        absent = [k for k in keys if not any(p == k or p.startswith(k + ".") for p, _ in items)]
        if absent:
            print(f"{args[1]} has no value for: {', '.join(absent)}")
            return 1
    if not items:
        if opt.get("--allow-empty"):
            print(f"ok: {args[1]} holds no numbers, and none are required")
            return 0
        print(f"{args[1]} holds no numbers to check")
        return 1
    missing = [(p, v) for p, v in items if not shown(v, text, decimals)]
    if missing:
        print(f"{args[0]} does not show these values from {args[1]} (copy them exactly, {decimals} decimals):")
        for p, v in missing:
            print(f"  {p} = {v}")
        return 1
    print(f"ok: all {len(items)} values from {args[1]} appear in {args[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
