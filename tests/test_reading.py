import itertools

import pytest

from cocotero import reading, store

BIB = """@article{x,
  author = {Brossard, Maxime},
  title = {AI-IMU Dead-Reckoning},
  year = {2020},
}"""

OTHER = """@article{y,
  author = {Vaswani, Ashish},
  title = {Attention Is All You Need},
  year = {2017},
}"""


@pytest.fixture()
def papers(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))
    store.store_paper(BIB)
    store.store_paper(OTHER)
    return store.get_paper("brossard2020"), store.get_paper("vaswani2017")


def test_add_queues_once(papers):
    first, _ = papers
    reading.add(first)
    reading.add(first)
    items = reading.entries()
    assert [item["key"] for item in items] == ["brossard2020"]
    assert items[0]["status"] == "queued"


def test_progress_marks_reading_and_keeps_note(papers):
    first, _ = papers
    reading.set_progress(first, "p5/20", "dense section 3")
    entry = reading.set_progress(first, "p8/20")
    assert entry["status"] == "reading"
    assert entry["progress"] == "p8/20"
    assert entry["note"] == "dense section 3"


def test_current_is_latest_unfinished(papers, monkeypatch):
    first, second = papers
    stamps = itertools.count()
    monkeypatch.setattr(reading, "_now", lambda: f"2026-10-02T08:00:{next(stamps):02d}")
    reading.set_progress(first, "p2")
    reading.set_progress(second, "40%")
    assert reading.current()["key"] == "vaswani2017"
    reading.finish(second)
    assert reading.current()["key"] == "brossard2020"


def test_current_none_when_nothing_in_progress(papers):
    first, _ = papers
    reading.add(first)
    assert reading.current() is None
