"""Tests for the CLI (argument parsing and command scaffolding)."""

import subprocess
import sys
import tempfile
import os


def test_cli_help():
    """Test that the CLI shows help when called without arguments."""
    result = subprocess.run(
        [sys.executable, "-m", "rag", "--help"],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 0
    assert "ingest" in result.stdout
    assert "ask" in result.stdout
    assert "eval" in result.stdout


def test_cli_subcommands():
    """Test that subcommands are recognized."""
    for cmd in ["ingest", "ask", "eval"]:
        result = subprocess.run(
            [sys.executable, "-m", "rag", cmd, "--help"],
            capture_output=True, text=True,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        assert result.returncode == 0, f"Subcommand '{cmd}' not recognized"


def test_cli_ingest_missing_corpus():
    """Test that ingest fails gracefully when corpus directory is missing."""
    result = subprocess.run(
        [sys.executable, "-m", "rag", "ingest", "/nonexistent/path"],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode != 0


def test_cli_ask_requires_user():
    """Test that ask command requires --user argument."""
    result = subprocess.run(
        [sys.executable, "-m", "rag", "ask", "What is a pod?"],
        capture_output=True, text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    # Should fail because --user is required
    assert result.returncode != 0
