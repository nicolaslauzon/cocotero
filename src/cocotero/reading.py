import json
from datetime import datetime
from pathlib import Path
from typing import Literal, TypedDict

from .config import load_config
from .store import Paper

Status = Literal["queued", "reading", "done", "dropped"]


class ReadingEntry(TypedDict):
    key: str
    title: str
    status: Status
    progress: str
    note: str
    added: str
    updated: str


def _list_path() -> Path:
    return Path(load_config()["library"]) / "reading" / "list.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def entries() -> list[ReadingEntry]:
    path = _list_path()
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _save(items: list[ReadingEntry]) -> None:
    path = _list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _upsert(paper: Paper, **changes: str) -> ReadingEntry:
    items = entries()
    entry = next((item for item in items if item["key"] == paper["key"]), None)
    if entry is None:
        now = _now()
        entry = {
            "key": paper["key"],
            "title": paper["title"],
            "status": "queued",
            "progress": "",
            "note": "",
            "added": now,
            "updated": now,
        }
        items.append(entry)
    entry.update(changes)
    if changes:
        entry["updated"] = _now()
    _save(items)
    return entry


def add(paper: Paper) -> ReadingEntry:
    return _upsert(paper)


def set_progress(paper: Paper, progress: str, note: str = "") -> ReadingEntry:
    changes = {"status": "reading", "progress": progress}
    if note:
        changes["note"] = note
    return _upsert(paper, **changes)


def finish(paper: Paper, note: str = "") -> ReadingEntry:
    changes = {"status": "done", "progress": "done"}
    if note:
        changes["note"] = note
    return _upsert(paper, **changes)


def drop(paper: Paper, note: str = "") -> ReadingEntry:
    changes = {"status": "dropped"}
    if note:
        changes["note"] = note
    return _upsert(paper, **changes)


def current() -> ReadingEntry | None:
    reading = [item for item in entries() if item["status"] == "reading"]
    return max(reading, key=lambda item: item["updated"], default=None)
