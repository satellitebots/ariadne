Build a small todo app in this folder (it is an empty git repo).

- Python 3, standard library only.
- A package `todo` with storage in a JSON file (default `todo.json` in the working folder, overridable).
- A command line: `python -m todo add "text"`, `python -m todo list` (shows id, done mark, text),
  `python -m todo done <id>`, `python -m todo remove <id>`, `python -m todo clear-done`.
- Clear errors for unknown ids; ids stay stable after removals.
- Tests with pytest in `tests/` covering storage and every command.
- A short README.md with usage.
- Commit the work when the tests pass.

Gates:
- run: python -m pytest -q
- Every command (add, list, done, remove, clear-done) has at least one test, and unknown ids give a clear error with a non-zero exit code
- After `add a`, `add b`, `remove 1`, `add c`, the ids listed are 2 and 3 (ids are never reused)
- README.md documents every command and the storage file override
- The work is committed in git (clean working tree)
