"""MCP server: data - profile, query and transform csv / sqlite (and parquet when pyarrow is present), stdlib only.

Run: python -m ariadne.data_mcp

One trick keeps this small and honest: every source becomes a table in an in-memory SQLite database, so a csv is
queried with the same SQL as a database and a transform is a SELECT written to a new file. Nothing here calls a
model. Absolute paths only: a relative path resolves somewhere the worker is not looking.
"""
import csv
import json
import sqlite3
from pathlib import Path

from mcp.server.mcpserver import MCPServer

server = MCPServer("ariadne-data", instructions=(
    "Read and shape data without loading it into your context: profile a csv/sqlite/parquet file, run SQL against "
    "it (a csv is a table called `data`), and write the result to a new file. Use this instead of printing large "
    "files; ask for the columns you need."))

SQL_FILE = (".db", ".sqlite", ".sqlite3")
FORBIDDEN = ("attach", "detach", "vacuum")     # a query may read; a transform may write its own output, nothing else


def _abs(path: str, what: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise ValueError(f"{what} must be an absolute path (relative paths resolve outside the workspace): {path}")
    if not p.exists():
        raise FileNotFoundError(f"no such file: {path}")
    return p


def _sniff(values):
    """int, real or text from the values seen; empty strings are NULL."""
    seen, real = 0, False
    for v in values:
        if v is None or str(v).strip() == "":
            continue
        seen += 1
        s = str(v).strip()
        try:
            int(s)
        except ValueError:
            try:
                float(s)
                real = True
            except ValueError:
                return "TEXT"
    if not seen:
        return "TEXT"
    return "REAL" if real else "INTEGER"


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _csv_table(conn, path: Path, name="data"):
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ValueError(f"{path.name} is empty")
    header = [h.strip() or f"col{i + 1}" for i, h in enumerate(rows[0])]
    body = [(r[:len(header)] + [""] * (len(header) - len(r[:len(header)]))) for r in rows[1:]]
    types = [_sniff([r[i] for r in body[:2000]]) for i in range(len(header))]
    conn.execute(f"CREATE TABLE {_quote(name)} (" + ", ".join(f"{_quote(h)} {t}" for h, t in zip(header, types)) + ")")
    sql = f"INSERT INTO {_quote(name)} VALUES (" + ",".join("?" * len(header)) + ")"

    def value(v, t):
        if v is None or str(v).strip() == "":
            return None
        return int(v) if t == "INTEGER" and str(v).strip().lstrip("+-").isdigit() else (
            float(v) if t == "REAL" else v)
    conn.executemany(sql, [[value(v, t) for v, t in zip(r, types)] for r in body])
    conn.commit()
    return name


def _parquet_table(conn, path: Path, name="data"):
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ValueError("reading parquet needs pyarrow, which this environment does not have: "
                         "`.venv/Scripts/python.exe -m pip install pyarrow` (then the same tool works). "
                         "csv and sqlite need nothing.")
    table = pq.read_table(path)
    cols = [str(c) for c in table.column_names]
    types = ["INTEGER" if str(t).startswith(("int", "uint")) else "REAL" if str(t).startswith("float") else "TEXT"
             for t in table.schema.types]
    conn.execute(f"CREATE TABLE {_quote(name)} (" + ", ".join(f"{_quote(c)} {t}" for c, t in zip(cols, types)) + ")")
    conn.executemany(f"INSERT INTO {_quote(name)} VALUES (" + ",".join("?" * len(cols)) + ")",
                     [list(r) for r in zip(*[table.column(i).to_pylist() for i in range(len(cols))])])
    conn.commit()
    return name


def _open(source: str):
    """(connection, [(table, rows)], close) - a sqlite file opens read-only as itself; anything else is copied in."""
    p = _abs(source, "source")
    if p.suffix.lower() in SQL_FILE:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                                             "ORDER BY name") if not r[0].startswith("sqlite_")]
        return conn, tables
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    name = _parquet_table(conn, p) if p.suffix.lower() == ".parquet" else _csv_table(conn, p)
    return conn, [name]


def _pick(tables, table=""):
    if table and table not in tables:
        raise ValueError(f"no table '{table}'; this source has: {', '.join(tables) or '(none)'}")
    if not tables:
        raise ValueError("this source has no tables")
    return table or tables[0]


@server.tool()
def list_tables(source: str) -> str:
    """What is in a data file: its tables (a csv or parquet file is one table, `data`) and their row counts."""
    try:
        conn, tables = _open(source)
        try:
            return json.dumps([{"table": t, "rows": conn.execute(f"SELECT count(*) FROM {_quote(t)}").fetchone()[0]}
                               for t in tables], indent=1)
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as e:
        return str(e)


@server.tool()
def profile(source: str, table: str = "", sample: int = 3) -> str:
    """Column-level profile of a table: type, nulls, distinct values, min/max for numbers, the `sample` first
    distinct values for text. Use it before writing SQL, instead of reading the file into the conversation."""
    try:
        conn, tables = _open(source)
        try:
            t = _pick(tables, table)
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_quote(t)})")]
            rows = conn.execute(f"SELECT count(*) FROM {_quote(t)}").fetchone()[0]
            out = {"table": t, "rows": rows, "columns": []}
            for c in cols:
                q = _quote(c)
                r = conn.execute(f"SELECT count({q}), count(DISTINCT {q}), min({q}), max({q}) FROM {_quote(t)}").fetchone()
                seen = [v[0] for v in conn.execute(
                    f"SELECT DISTINCT {q} FROM {_quote(t)} WHERE {q} IS NOT NULL LIMIT ?", (max(0, int(sample)),))]
                out["columns"].append({"name": c, "non_null": r[0], "nulls": rows - r[0], "distinct": r[1],
                                       "min": r[2], "max": r[3], "sample": seen})
            return json.dumps(out, indent=1, default=str)
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as e:
        return str(e)


@server.tool()
def query(source: str, sql: str, limit: int = 100) -> str:
    """Run a read-only SELECT against the file (a csv is `data`; a database keeps its own tables). Returns rows as
    JSON, capped at `limit` (default 100) - ask for the columns and aggregates you need, not everything."""
    first = sql.strip().lstrip("(").split(None, 1)[0].lower() if sql.strip() else ""
    if first not in ("select", "with", "explain"):
        return "query is read-only: it takes a SELECT (or WITH ... SELECT). Use transform to write a new file."
    try:
        conn, _tables = _open(source)
        try:
            cur = conn.execute(sql)
            rows = [dict(r) for r in cur.fetchmany(max(1, min(int(limit), 1000)))]
            more = " (more rows; raise limit or aggregate)" if cur.fetchone() is not None else ""
            return json.dumps({"rows": rows, "returned": len(rows)}, indent=1, default=str) + more
        finally:
            conn.close()
    except (OSError, ValueError, sqlite3.Error) as e:
        return f"SQL error: {e}" if isinstance(e, sqlite3.Error) else f"{type(e).__name__}: {e}"


@server.tool()
def transform(source: str, sql: str, output: str, table: str = "") -> str:
    """Run one SQL statement and write the result to `output` (.csv, .json or .db/.sqlite). A csv/sqlite result is
    written as a new table called `result`; a `.db` output keeps the file's own tables too. Absolute output path."""
    bad = [w for w in FORBIDDEN if w in sql.lower()]
    if bad:
        return f"{bad} is not allowed here"
    out = Path(output)
    if not out.is_absolute():
        return "output must be an absolute path inside your workspace"
    conn, tables = _open(source)
    try:
        sql = sql.strip()
        if sql.split(None, 1)[0].lower() in ("select", "with"):
            cur = conn.execute(sql)
            cols = [d[0] for d in cur.description or []]
            rows = [[r[c] for c in cols] for r in cur.fetchall()]
        else:                                                 # insert/update/create: the statement ran, then read back
            conn.execute(sql)
            t = _pick(tables, table) if tables else "result"
            cur = conn.execute(f"SELECT * FROM {_quote(t)}")
            cols = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchall()]
    except sqlite3.Error as e:
        conn.close()
        return f"SQL error: {e}"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        if out.suffix.lower() == ".csv":
            with open(out, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(cols)
                w.writerows(rows)
        elif out.suffix.lower() == ".json":
            out.write_text(json.dumps([dict(zip(cols, r)) for r in rows], indent=1, default=str), encoding="utf-8")
        elif out.suffix.lower() in SQL_FILE:
            dst = sqlite3.connect(str(out))
            dst.execute('DROP TABLE IF EXISTS "result"')
            dst.execute('CREATE TABLE "result" (' + ", ".join(f"{_quote(c)}" for c in cols) + ")")
            dst.executemany('INSERT INTO "result" VALUES (' + ",".join("?" * len(cols)) + ")", rows)
            dst.commit()
            dst.close()
        else:
            return "output must end in .csv, .json, .db, .sqlite or .sqlite3"
    finally:
        conn.close()
    return f"wrote {out} ({out.stat().st_size} bytes, {len(rows)} rows, columns: {', '.join(cols)})"


from .activity import instrument as _instrument  # noqa: E402
_instrument(server, "data")


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
