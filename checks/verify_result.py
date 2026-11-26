"""Gate: a check file ends in a verdict, and the verdict is PASS.

    python {checks}/verify_result.py CHECK.md

The worker runs the checks named in its plan and writes what it saw; the last 'RESULT:' line decides. A 'RESULT:
FAIL: why' fails the gate with the why, which the retry is given. Exits 1 with the reason, or prints a pass.
"""
import re
import sys


def main(argv):
    if not argv:
        print("usage: verify_result.py CHECK.md")
        return 2
    try:
        text = open(argv[0], encoding="utf-8").read()
    except OSError as e:
        print(f"cannot read {argv[0]}: {e}")
        return 1
    verdicts = re.findall(r"^\s*\**RESULT:?\**\s*(.+)$", text, re.M | re.I)
    if not verdicts:
        print(f"{argv[0]}: no 'RESULT: PASS' or 'RESULT: FAIL: <why>' line")
        return 1
    v = verdicts[-1].strip().strip("*").strip()
    if not v.upper().startswith("PASS"):
        print(f"{argv[0]}: {v}")
        return 1
    print(f"ok: {argv[0]}: RESULT: PASS ({len(re.findall(r'^\s*[-*] ', text, re.M))} checks listed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
