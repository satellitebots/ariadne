"""B6a: the `data` MCP server - csv and sqlite profiling, query and transform, with no dependency and no model."""
import csv
import json
import sqlite3

import pytest

from ariadne import data_mcp


@pytest.fixture
def sales(tmp_path):
    p = tmp_path / "sales.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["region", "units", "price", "note"])
        w.writerow(["north", "10", "2.5", "ok"])
        w.writerow(["south", "4", "3", ""])
        w.writerow(["north", "", "1.5", "rush"])
    return p


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "app.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE users(id INTEGER, name TEXT)")
    c.executemany("INSERT INTO users VALUES (?,?)", [(1, "ann"), (2, "bob")])
    c.commit()
    c.close()
    return p


def test_a_csv_is_a_table_called_data(sales):
    rows = json.loads(data_mcp.query(str(sales), "SELECT region, sum(units) AS units FROM data GROUP BY region "
                                                 "ORDER BY region"))
    assert rows["rows"] == [{"region": "north", "units": 10}, {"region": "south", "units": 4}]
    assert data_mcp.list_tables(str(sales)) == json.dumps([{"table": "data", "rows": 3}], indent=1)


def test_profile_types_the_columns_and_counts_nulls(sales):
    out = json.loads(data_mcp.profile(str(sales)))
    cols = {c["name"]: c for c in out["columns"]}
    assert out["rows"] == 3
    assert cols["units"]["nulls"] == 1 and cols["units"]["distinct"] == 2
    assert cols["price"]["min"] == 1.5 and cols["price"]["max"] == 3.0
    assert cols["region"]["sample"] == ["north", "south"]


def test_a_sqlite_file_keeps_its_own_tables(db):
    assert json.loads(data_mcp.list_tables(str(db))) == [{"table": "users", "rows": 2}]
    assert json.loads(data_mcp.query(str(db), "SELECT name FROM users WHERE id = 2"))["rows"] == [{"name": "bob"}]


def test_query_is_read_only(sales):
    out = data_mcp.query(str(sales), "DELETE FROM data")
    assert out.startswith("query is read-only")
    assert json.loads(data_mcp.query(str(sales), "SELECT count(*) AS n FROM data"))["rows"] == [{"n": 3}]


def test_transform_writes_csv_json_and_sqlite(sales, tmp_path):
    out_csv = tmp_path / "out" / "totals.csv"
    msg = data_mcp.transform(str(sales), "SELECT region, sum(units) AS units FROM data GROUP BY region",
                             str(out_csv))
    assert "wrote" in msg and out_csv.exists()
    assert out_csv.read_text(encoding="utf-8").splitlines()[0] == "region,units"

    out_json = tmp_path / "totals.json"
    data_mcp.transform(str(sales), "SELECT count(*) AS n FROM data", str(out_json))
    assert json.loads(out_json.read_text(encoding="utf-8")) == [{"n": 3}]

    out_db = tmp_path / "totals.db"
    data_mcp.transform(str(sales), "SELECT region FROM data", str(out_db))
    assert json.loads(data_mcp.list_tables(str(out_db))) == [{"table": "result", "rows": 3}]


def test_relative_paths_and_unknown_tables_are_refused(sales, tmp_path):
    assert "absolute" in data_mcp.query("sales.csv", "SELECT 1")
    assert "no table 'nope'" in data_mcp.profile(str(sales), table="nope")
    assert "absolute" in data_mcp.transform(str(sales), "SELECT 1", "relative.csv")


def test_a_broken_statement_comes_back_as_text_not_a_crash(sales, tmp_path):
    assert "SQL error" in data_mcp.query(str(sales), "SELECT nope FROM data")
    assert "SQL error" in data_mcp.transform(str(sales), "SELECT nope FROM data", str(tmp_path / "x.csv"))


def test_parquet_without_pyarrow_says_what_to_install(tmp_path):
    p = tmp_path / "x.parquet"
    p.write_bytes(b"PAR1")
    try:
        import pyarrow  # noqa: F401
        pytest.skip("pyarrow is installed here")
    except ImportError:
        pass
    msg = data_mcp.list_tables(str(p))
    assert "pyarrow" in msg and "pip install" in msg
