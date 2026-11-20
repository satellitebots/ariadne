"""B8: the content flow's citation gate - a source list that is checked, not trusted."""
import json

from ariadne import citations, flows as flowlib, paths

REPO_FLOWS = paths.ROOT / "flows"


def workspace(tmp_path, draft, sources=("- [S1] https://example.com/report - market size",),
              index=True):
    ws = tmp_path / "ws"
    (ws / "sources").mkdir(parents=True)
    (ws / "draft.md").write_text(draft, encoding="utf-8")
    if index:
        (ws / "sources" / "SOURCES.md").write_text("# Sources\n\n" + "\n".join(sources) + "\n", encoding="utf-8")
    return ws


def test_every_cited_marker_must_have_an_entry(tmp_path):
    ws = workspace(tmp_path, "The market is growing [S1]. It will double [S7].\n")
    out = citations.check(str(ws))
    assert out["ok"] is False and any("[S7]" in p and "draft.md" in p for p in out["problems"])
    assert out["cited"] == ["S1", "S7"] and out["listed"] == ["S1"]


def test_a_clean_piece_passes(tmp_path):
    ws = workspace(tmp_path, "The market is growing [S1].\n")
    out = citations.check(str(ws))
    assert out["ok"] is True and out["uncited"] == []
    assert citations.main([str(ws)]) == 0


def test_an_entry_nobody_cites_is_only_a_failure_in_strict_mode(tmp_path):
    ws = workspace(tmp_path, "The market grew [S1].\n",
                   sources=("- [S1] https://example.com - market size", "- [S2] https://b.example - prices"))
    loose = citations.check(str(ws), strict=False)
    assert loose["ok"] is True and loose["uncited"] == ["S2"]
    strict = citations.check(str(ws), strict=True)
    assert strict["ok"] is False and any("listed but never cited" in p and "[S2]" in p for p in strict["problems"])
    assert citations.main([str(ws), "--strict"]) == 1


def test_a_sources_folder_without_the_index_is_a_failure(tmp_path):
    ws = workspace(tmp_path, "text [S1]\n", index=False)
    out = citations.check(str(ws))
    assert out["ok"] is False and any("SOURCES.md is missing" in p for p in out["problems"])


def test_no_sources_folder_says_the_check_does_not_apply(tmp_path):
    ws = tmp_path / "plain"
    ws.mkdir()
    (ws / "draft.md").write_text("no references", encoding="utf-8")
    out = citations.check(str(ws))
    assert out["ok"] is False and "no sources/ folder" in out["problems"][0]
    assert citations.main([str(tmp_path / "nope")]) == 2


def test_the_index_itself_is_not_a_deliverable(tmp_path):
    ws = workspace(tmp_path, "fine [S1]\n")
    out = citations.check(str(ws))
    assert "SOURCES.md" not in json.dumps(out)               # the list cites itself; it is not checked as a claim


def test_the_content_flow_carries_the_pack_skill_and_the_check():
    fl = flowlib.load_flows(REPO_FLOWS)["content"]
    assert "reference-pack" in fl.skills
    assert (fl.folder / "skills" / "reference-pack" / "SKILL.md").exists()
    assert any(isinstance(c, dict) and "citations" in (c.get("run") or "") and c.get("when_exists") == "sources"
               for c in fl.checks)
    assert "reference pack" in fl.brief.lower()
