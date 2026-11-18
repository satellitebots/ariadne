"""Tests for todo.cli (via main())."""

from todo.cli import main


def _run(argv, tmp_path):
    """Run main() with --file pointed at tmp_path/<name>.json, return (exit, out, err)."""
    f = tmp_path / "test.json"
    exit_code = main(["--file", str(f)] + argv)
    return exit_code, f.read_text()


# -- add --

def test_add(tmp_path, capsys):
    exit_code = main(["--file", str(tmp_path / "a.json"), "add", "buy milk"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "added 1: buy milk" in captured.out


# -- list (empty) --

def test_list_empty(tmp_path, capsys):
    exit_code = main(["--file", str(tmp_path / "e.json"), "list"])
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "(nothing to do)"


# -- list (with items) --

def test_list_shows_items(tmp_path, capsys):
    main(["--file", str(tmp_path / "l.json"), "add", "alpha"])
    main(["--file", str(tmp_path / "l.json"), "add", "beta"])
    exit_code = main(["--file", str(tmp_path / "l.json"), "list"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1  [ ]  alpha" in out
    assert "2  [ ]  beta" in out


# -- list (with done mark) --

def test_list_shows_done_mark(tmp_path, capsys):
    main(["--file", str(tmp_path / "d.json"), "add", "task"])
    main(["--file", str(tmp_path / "d.json"), "done", "1"])
    main(["--file", str(tmp_path / "d.json"), "list"])
    out = capsys.readouterr().out
    assert "1  [x]  task" in out


# -- done --

def test_done(tmp_path, capsys):
    main(["--file", str(tmp_path / "do.json"), "add", "fix bug"])
    exit_code = main(["--file", str(tmp_path / "do.json"), "done", "1"])
    assert exit_code == 0
    assert "done 1: fix bug" in capsys.readouterr().out


# -- remove --

def test_remove(tmp_path, capsys):
    main(["--file", str(tmp_path / "rm.json"), "add", "old item"])
    exit_code = main(["--file", str(tmp_path / "rm.json"), "remove", "1"])
    assert exit_code == 0
    assert "removed 1: old item" in capsys.readouterr().out


# -- clear-done --

def test_clear_done(tmp_path, capsys):
    main(["--file", str(tmp_path / "cd.json"), "add", "keep"])
    main(["--file", str(tmp_path / "cd.json"), "add", "drop"])
    main(["--file", str(tmp_path / "cd.json"), "done", "2"])
    exit_code = main(["--file", str(tmp_path / "cd.json"), "clear-done"])
    assert exit_code == 0
    assert "cleared 1 done todo(s)" in capsys.readouterr().out


# -- unknown id errors --

def test_done_unknown_id(tmp_path, capsys):
    exit_code = main(["--file", str(tmp_path / "err.json"), "done", "99"])
    assert exit_code == 1
    assert "no todo item with id 99" in capsys.readouterr().err


def test_remove_unknown_id(tmp_path, capsys):
    exit_code = main(["--file", str(tmp_path / "err.json"), "remove", "99"])
    assert exit_code == 1
    assert "no todo item with id 99" in capsys.readouterr().err
