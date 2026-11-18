# todo

A small, stdlib-only Python CLI todo app backed by a JSON file.

## Usage

```
python -m todo --file <path> <command> [args]
```

`--file` is optional. Defaults to `todo.json` in the current directory.
Override via the `TODO_FILE` environment variable.

### Commands

| Command | Description | Example |
|---------|-------------|---------|
| `add <text>` | Add a new todo | `python -m todo add "Buy milk"` |
| `list` | Show all todos | `python -m todo list` |
| `done <id>` | Mark a todo as done | `python -m todo done 1` |
| `remove <id>` | Remove a todo entirely | `python -m todo remove 2` |
| `clear-done` | Remove all done todos | `python -m todo clear-done` |

### Storage

Todos are stored in a JSON file (default `./todo.json`):

```json
{
  "next_id": 4,
  "items": [
    {"id": 1, "text": "Buy milk", "done": true},
    {"id": 3, "text": "Walk dog", "done": false}
  ]
}
```

- `next_id` is a monotonic counter — ids are **never reused** after removal.
- Override the path with `--file` or the `TODO_FILE` environment variable.

### Errors

Unknown ids (for `done` or `remove`) print a clear error to stderr and return exit code 1.
