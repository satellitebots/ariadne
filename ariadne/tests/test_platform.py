"""Cross-platform pieces: lock files per platform, binary lookup, image tool guards, CLI dispatch."""
from ariadne import deps, image_mcp, paths


def test_every_platform_has_the_engine_binaries():
    for key in ("windows-x64", "linux-x64", "darwin-arm64"):
        names = {e["name"] for e in deps.bin_entries(key)}
        assert {"llama.cpp", "llama-swap", "pandoc", "sd.cpp"} <= names, key


def test_lock_rows_are_well_formed():
    for e in deps.bin_entries("windows-x64") + deps.bin_entries("linux-x64") + deps.bin_entries("darwin-arm64"):
        assert e["url"].startswith("https://github.com/") and len(e["sha256"]) == 64
    for m in deps.model_entries():
        assert m["url"].startswith("https://huggingface.co/") and len(m["sha256"]) == 64


def test_runtime_entries_extract_next_to_their_engine():
    rt = [e for e in deps.bin_entries("windows-x64") if e["name"].endswith("-rt")]
    assert rt and all(deps.bin_dir(e).name.startswith(e["name"][:-3] + "-") for e in rt)


def test_platform_key_shape():
    assert paths.platform_key() in ("windows-x64", "linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64")


def test_image_size_guard_and_missing_install(tmp_path, monkeypatch):
    assert "multiple of 64" in image_mcp.generate_image("x", str(tmp_path / "a.png"), width=500)
    assert "multiple of 64" in image_mcp.generate_image("x", str(tmp_path / "a.png"), height=2048)
    monkeypatch.setattr(paths, "BIN", tmp_path / "bin")
    assert "not installed" in image_mcp.generate_image("x", str(tmp_path / "a.png"))


def test_cli_help(capsys):
    from ariadne.__main__ import main
    assert main(["--help"]) == 0 and "doctor" in capsys.readouterr().out
