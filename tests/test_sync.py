import json
import subprocess

import pytest

from cocotero import cli, store, sync

BIB = """@article{x,
  author = {Brossard, Maxime and Barrau, Axel},
  title = {AI-IMU | Dead-Reckoning},
  year = {2020},
  doi = {10.1109/TIV.2020.2980758},
}"""

OTHER = """@article{y,
  author = {Vaswani, Ashish},
  title = {Attention Is All You Need},
  year = {2017},
}"""


@pytest.fixture()
def library(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    monkeypatch.setenv("COCOTERO_LIB", str(lib))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))
    for name in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{name}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{name}_EMAIL", "test@example.com")
    return lib


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_render_map_escapes_pipes_and_links_drive(library):
    store.store_paper(BIB)
    text = sync.render_map(store.list_papers(), {"brossard2020": "abc"})
    assert "| brossard2020 | 2020 | AI-IMU / Dead-Reckoning | Brossard et al." in text
    assert "https://drive.google.com/file/d/abc/view" in text


def test_render_map_marks_missing_pdf(library):
    store.store_paper(OTHER)
    rows = sync.render_map(store.list_papers(), {}).strip().splitlines()
    assert rows[-1].endswith("| none |")


def test_drive_ids_parses_lsjson(library, monkeypatch):
    listing = [
        {"Name": "brossard2020.pdf", "ID": "id1"},
        {"Name": "notes.txt", "ID": "id2"},
        {"Name": "vaswani2017.pdf"},
    ]
    monkeypatch.setattr(sync, "_check", lambda cmd, cwd: json.dumps(listing))
    assert sync.drive_ids(library, "gdrive:pdf") == {"brossard2020": "id1"}


def test_sync_without_git_or_remote_writes_map(library):
    store.store_paper(BIB)
    report = sync.sync_library()
    assert report == {
        "pulled": [],
        "fetched": [],
        "uploaded": False,
        "linked": 0,
        "pushed": False,
    }
    assert "brossard2020" in (library / "map.md").read_text()


def test_sync_with_remote_records_drive_links(library, monkeypatch):
    store.store_paper(BIB)
    config = library.parent / "config.toml"
    config.write_text('drive_remote = "gdrive:cocotero/pdf"\n')
    uploads = []
    monkeypatch.setattr(sync, "upload", lambda lib, remote: uploads.append(remote))
    monkeypatch.setattr(sync, "drive_ids", lambda lib, remote: {"brossard2020": "id9"})
    report = sync.sync_library()
    assert uploads == ["gdrive:cocotero/pdf"]
    assert report["linked"] == 1
    paper = store.get_paper("brossard2020")
    assert sync.drive_link(paper) == "https://drive.google.com/file/d/id9/view"


def test_sync_pulls_new_bibs_and_pushes(library, tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", str(origin), str(library))
    store.store_paper(BIB)
    _git(library, "add", "-A")
    _git(library, "commit", "-m", "init")
    _git(library, "push", "-u", "origin", "main")
    cloud = tmp_path / "cloud"
    _git(tmp_path, "clone", str(origin), str(cloud))
    (cloud / "bib" / "vaswani2017.bib").write_text(
        OTHER.replace("{y,", "{vaswani2017,")
    )
    _git(cloud, "add", "-A")
    _git(cloud, "commit", "-m", "cloud add")
    _git(cloud, "push")
    monkeypatch.setattr(sync, "download_pdf", lambda paper: {"pdf": None})
    report = sync.sync_library()
    assert report["pulled"] == ["vaswani2017"]
    assert report["pushed"]
    _git(cloud, "pull")
    assert "vaswani2017" in (cloud / "map.md").read_text()


def test_auto_sync_skipped_without_remote(library, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "sync_library", lambda: calls.append(1))
    cli._auto_sync()
    assert calls == []
