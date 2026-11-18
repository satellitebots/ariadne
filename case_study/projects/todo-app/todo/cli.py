"""Command-line interface for the todo app."""

import argparse
import sys

from .storage import TodoStore, UnknownIdError


def build_parser():
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A small todo list backed by a JSON file.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="path to the JSON storage file "
        "(default: $TODO_FILE or ./todo.json)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add a new todo")
    p_add.add_argument("text", help="text of the new todo")

    sub.add_parser("list", help="show all todos")

    p_done = sub.add_parser("done", help="mark a todo as done")
    p_done.add_argument("id", type=int, help="id of the todo to mark done")

    p_remove = sub.add_parser("remove", help="remove a todo")
    p_remove.add_argument("id", type=int, help="id of the todo to remove")

    sub.add_parser("clear-done", help="remove all done todos")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = TodoStore(args.file)

    try:
        if args.command == "add":
            item = store.add(args.text)
            print(f"added {item['id']}: {item['text']}")
        elif args.command == "list":
            items = store.list()
            if not items:
                print("(nothing to do)")
            for item in items:
                mark = "x" if item["done"] else " "
                print(f"{item['id']}  [{mark}]  {item['text']}")
        elif args.command == "done":
            item = store.mark_done(args.id)
            print(f"done {item['id']}: {item['text']}")
        elif args.command == "remove":
            item = store.remove(args.id)
            print(f"removed {item['id']}: {item['text']}")
        elif args.command == "clear-done":
            removed = store.clear_done()
            print(f"cleared {removed} done todo(s)")
    except UnknownIdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0
