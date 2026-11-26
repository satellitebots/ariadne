---
name: verify-locally
description: How to do a verify or check step - against the files already in the workspace, never redoing the research, never editing the sources of truth. Use for any step titled Verify, Check, Review or QA.
---
# Verify locally

A verify step checks what earlier steps made. It is not a second attempt at the work. (A verify step that went back
to the web ran out of turns and rewrote the data it was meant to check.)

- **Sources of truth are read-only.** `data/`, raw downloads, facts files and the sources ledger are what you check
  against. Never change them. If one is wrong, say so in your report; the step that made it is rerun.
- **Change only the deliverable** (the report, README, summary) to match the sources of truth.
- **Scripts first.** Run the step's check commands and any `python {checks}/...` gates yourself and fix what they
  print. Then read the deliverable claim by claim against the files.
- **No new research.** No web search, no new sources. A claim you cannot back from the workspace is removed or
  marked as unverified.
- **Leave a record.** End the deliverable with `VERIFIED: <n> claims checked` and, in your reply, list what you
  changed and why.
- **Clean up.** Delete scratch files you made (keep `scripts/` and `data/`).
