# Investigation flow - the coordination a small planner cannot infer

## Shape of the work
1. Turn the brief into **one question** and the list of things a good answer must contain.
2. Collect evidence from primary sources, recording source + version + date as you go.
3. Write `REPORT.md`: question, short answer, evidence with citations, inference clearly separated, open questions.
4. Check every claim in the report against the note you took when you found it.

## Models
- Default `gemma-4-26b-a4b` (MoE). One model for the whole investigation: the evidence lives in the conversation.
- Do not switch models mid-investigation; a switch re-reads everything and loses the thread.

## Tools
- `web_search` → `web_fetch` first; the browser only for JavaScript pages or something that needs a click.
- `terminal` + `search_files` when the subject is a codebase: read, quote path and line, do not change anything.
- `memory` for what earlier tasks already established about this subject.
- `export` (Pandoc) when the answer has to leave as a document.

## Evidence rules
- A fact without a source is an assumption, and the report says so.
- Prefer the specification, the paper, the filing, the project's own docs. A blog post is a lead, not evidence.
- Numbers carry units and the year they are from.
- "I could not verify this" is a finding. Write it instead of guessing.

## Gates
- Command gates are things like "REPORT.md exists", "every `http` link in REPORT.md appears in the sources list".
- A review gate should name the claims a reviewer must check and the sources they should find behind them.
