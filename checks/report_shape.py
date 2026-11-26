"""Gate: a report has the parts a reader needs and was verified (docs/WORKER-RECIPE.md, W4, W10).

    python {checks}/report_shape.py REPORT.md [--needs "answer,evidence,inference,unknown"] [--verified]

--needs: words that must each appear in some heading (case-insensitive). --verified: a line starting "VERIFIED:".
Prints what is missing and exits 1, or a one-line pass. Never raises.
"""
import re
import sys


def main(argv):
    path = next((a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--needs")), None)
    needs_arg = next((argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--needs"), "")
    if not path:
        print('usage: report_shape.py REPORT.md [--needs "answer,evidence"] [--verified]')
        return 2
    try:
        text = open(path, encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {path}: {e}")
        return 1
    heads = " ".join(m.group(1).lower() for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.M))
    needs = [w.strip().lower() for w in needs_arg.split(",") if w.strip()]
    problems = [f"no heading mentions '{w}'" for w in needs if w not in heads]
    if "--verified" in argv and not re.search(r"^\s*VERIFIED:", text, re.M):
        problems.append("no line starting 'VERIFIED:' (the verify step writes it)")
    if problems:
        print(f"{path}: " + "; ".join(problems))
        return 1
    print(f"ok: {path} has " + (", ".join(needs) if needs else "its parts") + (" and is verified" if "--verified" in argv else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
