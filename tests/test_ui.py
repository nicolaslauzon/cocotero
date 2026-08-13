import os
import shutil
import subprocess

import pytest

from cocotero.ui import MissingToolError, fzf_select, open_in_browser


def _fake_fzf(tmp_path, body):
    fzf = tmp_path / "fzf"
    fzf.write_text("#!/bin/sh\n" + body + "\n")
    fzf.chmod(0o755)
    return tmp_path


def test_fzf_select_returns_selection(tmp_path, monkeypatch):
    fake = _fake_fzf(
        tmp_path,
        "echo 'ui noise on stderr' >&2\n"
        "echo 'vaswani2017\t2017 Vaswani, Ashish — Attention'",
    )
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    assert fzf_select(["a", "b"]) == "vaswani2017\t2017 Vaswani, Ashish — Attention"


def test_fzf_select_cancelled(tmp_path, monkeypatch):
    fake = _fake_fzf(tmp_path, "exit 1")
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    assert fzf_select(["a"]) is None


def test_fzf_select_missing_tool(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(MissingToolError):
        fzf_select(["a"])


def test_open_in_browser_silences_stderr(monkeypatch):
    calls = []
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    open_in_browser("https://example.org/paper")
    args, kwargs = calls[0]
    assert args[0] == ["/usr/bin/xdg-open", "https://example.org/paper"]
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_open_in_browser_falls_back_to_webbrowser(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    opened = []
    monkeypatch.setattr("cocotero.ui.webbrowser.open", lambda url: opened.append(url))
    open_in_browser("https://example.org/paper")
    assert opened == ["https://example.org/paper"]
