import re
import shutil
import unicodedata
from pathlib import Path
from typing import Literal, TypedDict

from bibtexparser import Library, parse_string, write_string
from bibtexparser.model import Entry, Field

from .config import load_config


class StoreError(Exception):
    pass


class StoredPaper(TypedDict):
    key: str
    title: str
    folder: str
    pdf: str | None
    status: Literal["added", "skipped"]
    existing_key: str | None


class Paper(TypedDict):
    key: str
    year: str
    authors: str
    title: str
    url: str
    doi: str
    has_pdf: bool
    folder: str
    keywords: str


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "untitled"


def make_bibkey(first_author: str, year: str) -> str:
    return f"{slugify(first_author)}{slugify(year)}"


_ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-B]|\x1bE|\x1b."
)


def _sanitize_bibtex(bib_text: str) -> str:
    return _ANSI_ESCAPE.sub("", bib_text)


def first_author_lastname(author: str) -> str:
    first = author.split(" and ", maxsplit=1)[0].strip()
    last = first.split(",", maxsplit=1)[0].strip()
    return last.split()[-1] if last else ""


def _entries(bib_text: str) -> list[Entry]:
    try:
        library = parse_string(_sanitize_bibtex(bib_text))
    except Exception as exc:
        raise StoreError(f"Could not parse BibTeX: {exc}") from exc
    if not library.entries:
        raise StoreError("No BibTeX entries found in the input.")
    return library.entries


def _value(entry: Entry, field: str) -> str:
    found = entry.get(field)
    return found.value if found else ""


def _doi(entry: Entry) -> str:
    return _value(entry, "doi").strip().lower()


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _split_keywords(text: str) -> set[str]:
    return {keyword.strip().lower() for keyword in text.split(",") if keyword.strip()}


def _keywords(entry: Entry) -> set[str]:
    return _split_keywords(_value(entry, "keywords"))


def _keywords_text(keywords: set[str]) -> str:
    return ", ".join(sorted(keywords))


def _unique_key(library: Path, wanted: str) -> str:
    if not (library / wanted).exists():
        return wanted
    n = 2
    while (library / f"{wanted}-{n}").exists():
        n += 1
    return f"{wanted}-{n}"


def _scan(library: Path) -> list[tuple[Path, Entry]]:
    found = []
    for entry_bib in sorted(library.glob("*/entry.bib")):
        try:
            for entry in _entries(entry_bib.read_text(encoding="utf-8")):
                found.append((entry_bib.parent, entry))
        except StoreError:
            continue
    return found


def find_by_doi(library: Path, doi: str) -> Path | None:
    doi = doi.strip().lower()
    if not doi:
        return None
    for folder, entry in _scan(library):
        if _doi(entry) == doi:
            return folder
    return None


def find_by_title(library: Path, title: str) -> Path | None:
    normalized = _normalized_title(title)
    if not normalized:
        return None
    for folder, entry in _scan(library):
        if _normalized_title(_value(entry, "title")) == normalized:
            return folder
    return None


def normalize_library() -> None:
    library = Path(load_config()["library"])
    for folder in sorted(library.glob("*")):
        entry_bib = folder / "entry.bib"
        if not entry_bib.is_file():
            continue
        try:
            entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
        except StoreError:
            continue
        wanted = make_bibkey(
            first_author_lastname(_value(entry, "author")), _value(entry, "year")
        )
        if wanted == folder.name:
            continue
        target = _unique_key(library, wanted)
        entry.key = target
        entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")
        shutil.move(folder, library / target)


def _skipped_paper(folder: Path) -> StoredPaper:
    entry = _entries((folder / "entry.bib").read_text(encoding="utf-8"))[0]
    pdf = folder / "paper.pdf"
    return {
        "key": entry.key,
        "title": _value(entry, "title"),
        "folder": str(folder),
        "pdf": str(pdf) if pdf.is_file() else None,
        "status": "skipped",
        "existing_key": entry.key,
    }


def store_paper(bib_text: str, pdf_path: str | None = None) -> StoredPaper:
    library = Path(load_config()["library"])
    normalize_library()
    entry = _entries(bib_text)[0]

    doi = _doi(entry)
    if doi and (existing := find_by_doi(library, doi)):
        return _skipped_paper(existing)
    if not doi and (existing := find_by_title(library, _value(entry, "title"))):
        return _skipped_paper(existing)

    key = _unique_key(library, make_bibkey(
        first_author_lastname(_value(entry, "author")), _value(entry, "year")
    ))
    folder = library / key
    folder.mkdir(parents=True, exist_ok=False)

    entry.key = key
    if doi and not entry.get("url"):
        entry.set_field(Field("url", _doi_url(doi)))
    if pdf_path and not entry.get("file"):
        entry.set_field(Field("file", ":paper.pdf:PDF"))

    (folder / "entry.bib").write_text(write_string(Library([entry])), encoding="utf-8")

    stored_pdf = None
    if pdf_path:
        src = Path(pdf_path).expanduser()
        if not src.is_file():
            raise StoreError(f"PDF not found: {src}")
        shutil.copy2(src, folder / "paper.pdf")
        stored_pdf = str(folder / "paper.pdf")

    return {
        "key": key,
        "title": _value(entry, "title"),
        "folder": str(folder),
        "pdf": stored_pdf,
        "status": "added",
        "existing_key": None,
    }


def store_papers(bib_text: str, pdf_path: str | None = None) -> list[StoredPaper]:
    entries = _entries(bib_text)
    return [store_paper(write_string(Library([entry])), pdf_path=pdf_path) for entry in entries]


def list_papers(category: str | None = None) -> list[Paper]:
    library = Path(load_config()["library"])
    normalize_library()
    wanted = category.lower() if category else None
    papers: list[Paper] = []
    for entry_bib in sorted(library.glob("*/entry.bib")):
        try:
            entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
        except StoreError:
            continue
        paper: Paper = {
            "key": entry.key,
            "year": _value(entry, "year"),
            "authors": _value(entry, "author"),
            "title": _value(entry, "title"),
            "url": _value(entry, "url"),
            "doi": _value(entry, "doi"),
            "has_pdf": (entry_bib.parent / "paper.pdf").is_file(),
            "folder": str(entry_bib.parent),
            "keywords": _value(entry, "keywords"),
        }
        if wanted and wanted not in _split_keywords(paper["keywords"]):
            continue
        papers.append(paper)
    return papers


def get_paper(key: str) -> Paper | None:
    return next((paper for paper in list_papers() if paper["key"] == key), None)


def _entry_and_folder(key: str) -> tuple[Path, Entry]:
    for folder, entry in _scan(Path(load_config()["library"])):
        if entry.key == key:
            return folder, entry
    raise StoreError(f"No paper with key '{key}'.")


def keywords(key: str) -> set[str]:
    _, entry = _entry_and_folder(key)
    return _keywords(entry)


def set_keywords(key: str, value: set[str]) -> None:
    folder, entry = _entry_and_folder(key)
    entry.fields = [field for field in entry.fields if field.key != "keywords"]
    if value:
        entry.set_field(Field("keywords", _keywords_text(value)))
    (folder / "entry.bib").write_text(write_string(Library([entry])), encoding="utf-8")


def toggle_keyword(key: str, category: str) -> bool:
    current = keywords(key)
    if category in current:
        set_keywords(key, current - {category})
        return False
    set_keywords(key, current | {category})
    return True


def list_categories() -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for paper in list_papers():
        for category in _split_keywords(paper["keywords"]):
            counts[category] = counts.get(category, 0) + 1
    return sorted(counts.items())


def search_index(category: str | None = None) -> list[str]:
    return [
        f"{paper['key']}\t{paper['year']} {paper['authors']} — {paper['title']}"
        for paper in list_papers(category)
    ]


def resolve_paper_url(paper: Paper) -> str:
    if paper["url"]:
        return paper["url"]
    if paper["doi"]:
        return _doi_url(paper["doi"])
    raise StoreError(f"No URL available for '{paper['key']}'.")