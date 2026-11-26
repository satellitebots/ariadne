"""Gate: a data file exists, has enough rows, and its newest row is recent (docs/WORKER-RECIPE.md, W1, W8).

    python {checks}/fresh_data.py data/prices.csv [--date-col date] [--min-rows 50] [--max-age-days 7]

CSV (by header) or JSON (a list of objects). Prints what is wrong and exits 1, or a one-line pass. Never raises.
"""
import csv
import datetime as dt
import json
import sys


def main(argv):
    path = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))), None)
    opt = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
    if not path:
        print("usage: fresh_data.py FILE [--date-col date] [--min-rows 50] [--max-age-days 7]")
        return 2
    try:
        col, need, age = opt.get("--date-col", "date"), int(opt.get("--min-rows", 1)), int(opt.get("--max-age-days", 7))
        if path.endswith(".json"):
            rows = json.load(open(path, encoding="utf-8"))
            rows = rows if isinstance(rows, list) else []
        else:
            rows = list(csv.DictReader(open(path, encoding="utf-8")))
    except (OSError, ValueError) as e:
        print(f"cannot read {path}: {e}")
        return 1
    dates = []
    for r in rows:
        try:
            dates.append(dt.date.fromisoformat(str(r.get(col, ""))[:10]))
        except (ValueError, AttributeError):
            pass
    problems = []
    if len(rows) < need:
        problems.append(f"{len(rows)} rows; at least {need} needed")
    if not dates:
        problems.append(f"no ISO dates in column '{col}'")
    elif (dt.date.today() - max(dates)).days > age:
        problems.append(f"newest row is {max(dates)}, more than {age} days before today ({dt.date.today()})")
    if problems:
        print(f"{path}: " + "; ".join(problems))
        return 1
    print(f"ok: {path} has {len(rows)} rows, newest {max(dates)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
