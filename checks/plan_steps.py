"""Gate: a plan file has a '## Steps' list the engine can repeat over (`each:` steps).

    python {checks}/plan_steps.py PLAN.md [--min 2] [--max 8]

The items are the top-level list lines ('- x', '1. x', '- [ ] x') under a heading containing the word "Steps";
indented lines are details. Same rule as ariadne.spec.plan_items (a test keeps them equal). Each item is one line of
at most 300 characters. Prints what is wrong and exits 1, or a one-line pass. Never raises.
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
    lo, hi = _arg(argv, "--min", 1), _arg(argv, "--max", 25)
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 1
    items = plan_items(text)
    problems = []
    if not re.search(r"^\s*#{1,6}\s+.*\bsteps\b", text, re.I | re.M):
        problems.append("no heading with the word 'Steps' (write '## Steps' and the list under it)")
    elif not items:
        problems.append("the '## Steps' section has no list items ('1. ...' or '- ...', not indented)")
    elif not lo <= len(items) <= hi:
        problems.append(f"{len(items)} steps; between {lo} and {hi} (merge small ones or split big ones)")
    long = [i for i, x in enumerate(items, 1) if len(x) > 300]
    if long:
        problems.append(f"step(s) {', '.join(map(str, long))} are over 300 characters: one line each; details go "
                        "on indented lines under it")
    if problems:
        print(f"{path}: " + "; ".join(problems))
        return 1
    print(f"ok: {path} has {len(items)} steps: " + " | ".join(x[:40] for x in items))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
