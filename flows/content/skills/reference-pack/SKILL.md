---
name: reference-pack
description: Build a source pack, cite every borrowed claim, and pass the citation gate in the content flow.
---
# Reference pack

The person judges a piece by its sources, not by its confidence. Build the pack first; drafting without it is what
produces confident text nobody can check.

## Layout (in the workspace)
```
sources/
  SOURCES.md        one line per source: - [S1] <url or citation> - what it supports
  S1.md             the fetched text (web_fetch output), one file per source
draft.md            the piece, with markers like "grew 12% [S2]"
```

## Build it
1. `web_fetch` each reference and save the text to `sources/S<n>.md`. Keep the URL in the first line.
2. Write `SOURCES.md` as you go; an id is assigned once and never reused or renumbered.
3. If a source contradicts another, say so on both lines and let the piece reflect the disagreement instead of
   picking the convenient number.

## Cite
- Every fact, number, quote or attributed opinion carries its marker at the end of the sentence: `... [S1]`.
- Two sources for one claim: `[S1][S3]`. A source used for background only still gets an entry and a mention.
- Never cite a source you did not read, and never put a marker on a claim the source does not actually support.

## Fact-check pass (before the report)
For each marker: open the source file, find the sentence, compare it with the claim. Then either keep it, narrow it
("most" instead of "all"), or drop it. Record the verdict on the source's line: `confirmed` or `narrowed to ...`.
The report names what could not be confirmed.

## The gate
`python -m ariadne.citations .` (the flow runs it when `sources/` exists). It fails on a marker with no entry and,
in strict mode, on an entry nobody cites. Fix the deliverable or the pack; do not remove markers to make it pass.
