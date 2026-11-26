"""Gate: a plan file has a '## Steps' list the engine can repeat over (`each:` steps). That is the only fact it
enforces; the rest are notes for the worker (it guides, it never fences).

    python {checks}/plan_steps.py PLAN.md [--min N] [--max N]

The items are the top-level list lines ('- x', '1. x', '- [ ] x') under a heading containing the word "Steps";
indented lines are details. Same rule as ariadne.spec.plan_items (a test keeps them equal). Fails (exit 1) only when
there is no such list; --min/--max and very long lines are printed as notes. Never raises.
"""
import re
import sys


def plan_items(text):
    items, inside = [], False
    for line in text.splitlines():
        h = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if h:
            if inside:
                break
            inside = bool(re.search(r"\bsteps\b", h.group(1), re.I))
            continue
        m = re.match(r"^(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s*)?(.+?)\s*$", line) if inside else None
        if m:
            items.append(m.group(1))
    return items


def _arg(argv, name, default):
    return int(argv[argv.index(name) + 1]) if name in argv else default


def main(argv):
    path = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or not argv[i - 1].startswith("--"))), None)
    if not path:
        print("usage: plan_steps.py PLAN.md [--min 2] [--max 8]")
        return 2
    lo, hi = _arg(argv, "--min", 1), _arg(argv, "--max", 10 ** 6)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 1
    items = plan_items(text)
    if not re.search(r"^\s*#{1,6}\s+.*\bsteps\b", text, re.I | re.M):
        print(f"{path}: no heading with the word 'Steps' (write '## Steps' and the list under it)")
        return 1
    if not items:
        print(f"{path}: the '## Steps' section has no list items ('1. ...' or '- ...', not indented)")
        return 1
    notes = []
    if not lo <= len(items) <= hi:
        notes.append(f"{len(items)} steps (the task suggests {lo} to {hi})")
    long = [i for i, x in enumerate(items, 1) if len(x) > 300]
    if long:
        notes.append(f"step(s) {', '.join(map(str, long))} are long; each becomes one step's whole brief")
    print(f"ok: {path} has {len(items)} steps: " + " | ".join(x[:40] for x in items)
          + ("".join(f"\nnote: {n}" for n in notes)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
