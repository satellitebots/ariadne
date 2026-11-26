---
name: facts-first
description: Any number, date or measure in a deliverable comes from a facts file a script wrote, and prose copies it. Use whenever a report, README or summary states figures (prices, changes, counts, scores, timings).
---
# Facts first

Numbers you compute in your head or in prose come out wrong: a close reported as a low, a fraction as a percent,
"one month" measured two ways in one report. So numbers are produced once, by code, and copied everywhere else.

1. **A script computes them.** `scripts/facts.py` (or the data step's script) reads the raw data and writes
   `data/facts.json`. Every value the deliverable will state is in it, rounded as it will be shown (2 decimals).
2. **Say what each one is.** Next to each value: its unit, its date or window, and the formula when it is derived.
   ```json
   {"change_1m": {"pct": -11.92, "unit": "percent", "from": "2026-10-26", "to": "2026-11-24",
                  "formula": "(close[-1] / close[-22] - 1) * 100"},
    "low_3m": {"value": 264.22, "unit": "USD", "date": "2026-11-20", "formula": "min(low[-63:])"}}
   ```
   Use exactly the definitions the step gives (units, windows, columns). If none is given, choose one, write it in
   the formula, and use it everywhere.
3. **Prose copies.** When you write, copy each value from the facts file with its unit and date. Never round
   differently, recompute, or derive a new number in the text; if the text needs a number the file lacks, add it to
   the script and rerun it.
4. **The check.** `python {checks}/facts_in_report.py REPORT.md data/facts.json` fails if a value is missing or
   written differently. Run it before you finish.
