---
name: investigate
description: How the investigation flow answers a question - bound it, gather from primary sources, separate fact from inference, name what is unknown, cite everything.
---
# Investigate

The deliverable is a report a sceptical reader can check, not a confident answer. Most of the work is deciding
what would count as evidence before you go looking for it.

## Bound the question first
1. Write the question as one sentence, then write what a good answer would have to contain (numbers, a name, a
   date, a comparison, a mechanism).
2. List what you already know and what you are assuming. Assumptions go in the report.
3. If the brief asks several questions, answer them in order and say which are still open.

## Gather
- `web_search`, then `web_fetch`. The browser is only for pages that need JavaScript or a click.
- Prefer primary sources: the project's own docs, the specification, the paper, the filing. A blog post is a lead,
  not evidence. When only secondary sources exist, say so.
- For a codebase: read the files, `search_files` for the mechanism, and quote the path and line.
- Record the URL, the version and the date next to every fact as you collect it. A fact you cannot cite does not
  go in the report as a fact.

## Write
- `REPORT.md` in the workspace, with: the question, the short answer, the evidence (each with its source),
  what is inference rather than fact, what is unknown or contested, and what would change the answer.
- Numbers with units and the year they are from. Quote exact wording when the wording matters.
- Separate "the docs say" from "I concluded". Never present the second as the first.

## Do not
- Do not invent a citation, a version or a number. If you could not verify it, write that you could not.
- Do not answer a different, easier question because the real one is hard; say what is missing.
- Do not run installs, builds or test suites. This flow reads and writes documents, it does not change the system.
