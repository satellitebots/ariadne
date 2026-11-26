"""The shared gate scripts (checks/, docs/WORKER-RECIPE.md): each catches the failure it was written for."""
import datetime as dt
import json
import subprocess
import sys

from ariadne import flows as flowlib, paths, spec as speclib

CHECKS = paths.ROOT / "checks"


def run(script, *args, cwd):
    p = subprocess.run([sys.executable, str(CHECKS / script), *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_facts_in_report_catches_a_recomputed_number(tmp_path):
    (tmp_path / "facts.json").write_text(json.dumps({"close": 279.05, "low_3m": {"value": 264.22, "date": "2026-11-20"},
                                                     "change_1m": {"pct": -11.92, "from": "2026-10-26"}}))
    (tmp_path / "R.md").write_text("Close $279.05; down 11.92% since 2026-10-26; 3-month low $265.29.")
    code, out = run("facts_in_report.py", "R.md", "facts.json", cwd=tmp_path)
    assert code == 1 and "low_3m.value = 264.22" in out and "close" not in out.split("decimals):")[1]
    (tmp_path / "R.md").write_text("Close $279.05; down 11.92%; 3-month low $264.22 (2026-11-20).")
    assert run("facts_in_report.py", "R.md", "facts.json", cwd=tmp_path)[0] == 0
    (tmp_path / "empty.json").write_text("{}")
    assert run("facts_in_report.py", "R.md", "empty.json", cwd=tmp_path)[0] == 1
    assert run("facts_in_report.py", "R.md", "empty.json", "--allow-empty", cwd=tmp_path)[0] == 0


def test_sources_ledger_catches_wrong_publisher_old_dates_and_loose_lines(tmp_path):
    today = dt.date(2026, 11, 25)
    good = ["- https://www.reuters.com/x | Reuters | earnings | 2026-11-20",
            "- https://www.sec.gov/edgar/y | SEC EDGAR | 10-Q | 2026-11-18",
            "- https://abc.xyz/investor/z | Alphabet (abc.xyz) | results | 2026-11-15"]
    (tmp_path / "S.md").write_text("\n".join(good))
    assert run("sources_ledger.py", "S.md", "--within-days", "14", "--today", str(today), cwd=tmp_path)[0] == 0
    bad = good + ["- https://blockonomi.com/a | BNN Bloomberg | low | 2026-11-20",
                  "- https://www.reuters.com/old | Reuters | old | 2026-09-01",
                  "- https://example.com/loose - no pipes here"]
    (tmp_path / "S.md").write_text("\n".join(bad))
    code, out = run("sources_ledger.py", "S.md", "--within-days", "14", "--today", str(today), cwd=tmp_path)
    assert code == 1 and "does not match the site blockonomi.com" in out and "older than 14 days" in out
    assert "write it as" in out


def test_fresh_data_and_report_shape(tmp_path):
    rows = ["date,close"] + [f"{dt.date.today() - dt.timedelta(days=i)},1" for i in range(60, 0, -1)]
    (tmp_path / "p.csv").write_text("\n".join(rows))
    assert run("fresh_data.py", "p.csv", "--min-rows", "50", "--max-age-days", "7", cwd=tmp_path)[0] == 0
    assert run("fresh_data.py", "p.csv", "--min-rows", "100", cwd=tmp_path)[0] == 1
    (tmp_path / "R.md").write_text("# Answer\nx\n## Evidence\ny\n")
    assert run("report_shape.py", "R.md", "--needs", "answer,evidence", cwd=tmp_path)[0] == 0
    code, out = run("report_shape.py", "R.md", "--needs", "answer,unknown", "--verified", cwd=tmp_path)
    assert code == 1 and "unknown" in out and "VERIFIED" in out


def test_definitions_and_skills_name_the_checks_folder():
    assert speclib.fill("python {checks}/x.py", {}) == f"python {(paths.ROOT / 'checks').as_posix()}/x.py"
    fl = flowlib.load_flows()["investigation"]
    sp, problems = speclib.from_template(fl, name="t-recipe", workspace=str(paths.ROOT / "sandbox" / "t"))
    sp["params"] = {"question": "q", "must_contain": "m", "within_days": "14"}
    speclib.validate(sp, flowlib.load_flows())          # {checks} needs no param
    assert any("{checks}/facts_in_report.py" in (st.get("gate") or {}).get("text", "") for st in sp["steps"])
