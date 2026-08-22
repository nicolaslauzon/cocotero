import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from bibtexparser import Library, parse_string, write_string
from bibtexparser.model import Entry, Field

from .config import load_config

logging.getLogger("bibtexparser").setLevel(logging.ERROR)


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
    arxiv: str
    has_pdf: bool
    folder: str
    categories: str


class CleanReport(TypedDict):
    removed: list[tuple[str, str]]
    kept: int


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "untitled"


def make_bibkey(first_author: str, year: str) -> str:
    return f"{slugify(first_author)}{slugify(year)}"


def _bib_dir(library: Path) -> Path:
    return library / "bib"


def _pdf_dir(library: Path) -> Path:
    return library / "pdf"


def _bib_path(library: Path, key: str) -> Path:
    return _bib_dir(library) / f"{key}.bib"


def _pdf_path(library: Path, key: str) -> Path:
    return _pdf_dir(library) / f"{key}.pdf"


_ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-B]|\x1bE|\x1b."
)


def _sanitize_bibtex(bib_text: str) -> str:
    return _ANSI_ESCAPE.sub("", bib_text)


def _split_blocks(bib_text: str) -> list[str]:
    blocks: list[str] = []
    depth = 0
    current: list[str] = []
    for char in bib_text:
        current.append(char)
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                blocks.append("".join(current))
                current = []
    if current:
        blocks.append("".join(current))
    return [block for block in blocks if block.strip().startswith("@")]


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
    for entry in library.entries:
        for field in entry.fields:
            field.key = field.key.lower()
    return library.entries


def _value(entry: Entry, field: str) -> str:
    found = entry.get(field)
    return found.value if found else ""


def _normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi)
    doi = doi.removeprefix("doi:").strip()
    return doi.rstrip(".,;:) ")


def _doi(entry: Entry) -> str:
    return _normalize_doi(_value(entry, "doi"))


def _doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _split_keywords(text: str) -> set[str]:
    return {keyword.strip().lower() for keyword in text.split(",") if keyword.strip()}


def _keywords(entry: Entry) -> set[str]:
    return _split_keywords(_value(entry, "category"))


def _keywords_text(keywords: set[str]) -> str:
    return ", ".join(sorted(keywords))


def _unique_key(library: Path, wanted: str) -> str:
    if not _bib_path(library, wanted).exists():
        return wanted
    n = 2
    while _bib_path(library, f"{wanted}-{n}").exists():
        n += 1
    return f"{wanted}-{n}"


def _scan(library: Path) -> list[tuple[Path, Entry]]:
    found = []
    bibs = sorted(_bib_dir(library).glob("*.bib"), key=lambda path: path.stem)
    for entry_bib in bibs:
        try:
            for entry in _entries(entry_bib.read_text(encoding="utf-8")):
                found.append((entry_bib, entry))
        except StoreError:
            continue
    return found


@dataclass
class LibraryIndex:
    by_doi: dict[str, Path]
    by_title: dict[str, Path]


def _build_index(library: Path) -> LibraryIndex:
    by_doi: dict[str, Path] = {}
    by_title: dict[str, Path] = {}
    for entry_bib, entry in _scan(library):
        doi = _doi(entry)
        if doi:
            by_doi.setdefault(doi, entry_bib)
        title = _normalized_title(_value(entry, "title"))
        if title:
            by_title.setdefault(title, entry_bib)
    return LibraryIndex(by_doi=by_doi, by_title=by_title)


def find_by_doi(library: Path, doi: str) -> Path | None:
    doi = doi.strip().lower()
    if not doi:
        return None
    for entry_bib, entry in _scan(library):
        if _doi(entry) == doi:
            return entry_bib
    return None


def find_by_title(library: Path, title: str) -> Path | None:
    normalized = _normalized_title(title)
    if not normalized:
        return None
    for entry_bib, entry in _scan(library):
        if _normalized_title(_value(entry, "title")) == normalized:
            return entry_bib
    return None


def normalize_library() -> None:
    library = Path(load_config()["library"])
    for entry_bib in sorted(_bib_dir(library).glob("*.bib")):
        try:
            entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
        except StoreError:
            continue
        wanted = make_bibkey(
            first_author_lastname(_value(entry, "author")), _value(entry, "year")
        )
        if wanted == entry_bib.stem:
            continue
        target = _unique_key(library, wanted)
        entry.key = target
        _bib_path(library, target).write_text(
            write_string(Library([entry])), encoding="utf-8"
        )
        old_pdf = _pdf_path(library, entry_bib.stem)
        if old_pdf.is_file():
            shutil.move(old_pdf, _pdf_path(library, target))
        entry_bib.unlink()


def _skipped_paper(entry_bib: Path) -> StoredPaper:
    entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
    pdf = _pdf_path(entry_bib.parent.parent, entry.key)
    return {
        "key": entry.key,
        "title": _value(entry, "title"),
        "folder": str(entry_bib.parent.parent),
        "pdf": str(pdf) if pdf.is_file() else None,
        "status": "skipped",
        "existing_key": entry.key,
    }


def _store_entry(
    entry: Entry,
    library: Path,
    index: LibraryIndex,
    pdf_path: str | None = None,
) -> StoredPaper:
    entry.fields = [field for field in entry.fields if field.key != "keywords"]

    doi = _doi(entry)
    title = _normalized_title(_value(entry, "title"))
    existing = index.by_doi.get(doi) if doi else None
    if existing is None and not doi and title:
        existing = index.by_title.get(title)
    if existing is not None:
        return _skipped_paper(existing)

    if pdf_path and not Path(pdf_path).expanduser().is_file():
        raise StoreError(f"PDF not found: {Path(pdf_path).expanduser()}")

    key = _unique_key(
        library,
        make_bibkey(
            first_author_lastname(_value(entry, "author")), _value(entry, "year")
        ),
    )
    entry.key = key
    if doi and not entry.get("url"):
        entry.set_field(Field("url", _doi_url(doi)))
    _bib_dir(library).mkdir(parents=True, exist_ok=True)
    entry_bib = _bib_path(library, key)
    entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")

    stored_pdf = link_pdf(key, pdf_path) if pdf_path else None

    if doi:
        index.by_doi[doi] = entry_bib
    if title:
        index.by_title[title] = entry_bib

    return {
        "key": key,
        "title": _value(entry, "title"),
        "folder": str(library),
        "pdf": stored_pdf,
        "status": "added",
        "existing_key": None,
    }


def store_paper(bib_text: str, pdf_path: str | None = None) -> StoredPaper:
    library = Path(load_config()["library"])
    normalize_library()
    entry = _entries(bib_text)[0]
    return _store_entry(entry, library, _build_index(library), pdf_path=pdf_path)


def store_papers(bib_text: str, pdf_path: str | None = None) -> list[StoredPaper]:
    blocks = _split_blocks(_sanitize_bibtex(bib_text))
    if not blocks:
        raise StoreError("No BibTeX entries found in the input.")
    library = Path(load_config()["library"])
    normalize_library()
    index = _build_index(library)
    results = []
    for block in blocks:
        try:
            entry = _entries(block)[0]
        except StoreError:
            continue
        results.append(_store_entry(entry, library, index, pdf_path=pdf_path))
    return results


def link_pdf(key: str, pdf_path: str) -> str:
    entry_bib, entry = _entry_and_bib(key)
    src = Path(pdf_path).expanduser()
    if not src.is_file():
        raise StoreError(f"PDF not found: {src}")
    library = entry_bib.parent.parent
    target = _pdf_path(library, key)
    _pdf_dir(library).mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    if not entry.get("file"):
        entry.set_field(Field("file", f":pdf/{key}.pdf:PDF"))
    entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")
    return str(target)


def set_doi(key: str, doi: str) -> None:
    entry_bib, entry = _entry_and_bib(key)
    doi = _normalize_doi(doi)
    if not doi:
        return
    if not entry.get("doi"):
        entry.set_field(Field("doi", doi))
    if not entry.get("url"):
        entry.set_field(Field("url", _doi_url(doi)))
    entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")


def _arxiv_id(entry: Entry) -> str:
    match = re.search(r"\d{4}\.\d{4,5}(?:v\d+)?", _value(entry, "eprint"))
    if match:
        return match.group(0)
    match = re.search(
        r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+)", _value(entry, "url"), re.IGNORECASE
    )
    return match.group(1) if match else ""


def _paper(entry_bib: Path) -> Paper:
    entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
    return {
        "key": entry.key,
        "year": _value(entry, "year"),
        "authors": _value(entry, "author"),
        "title": _value(entry, "title"),
        "url": _value(entry, "url"),
        "doi": _normalize_doi(_value(entry, "doi")),
        "arxiv": _arxiv_id(entry),
        "has_pdf": _pdf_path(entry_bib.parent.parent, entry.key).is_file(),
        "folder": str(entry_bib.parent.parent),
        "categories": _value(entry, "category"),
    }


def paper_from_result(result: StoredPaper) -> Paper:
    library = Path(result["folder"])
    return _paper(_bib_path(library, result["key"]))


def list_papers(category: str | None = None) -> list[Paper]:
    library = Path(load_config()["library"])
    normalize_library()
    wanted = category.lower() if category else None
    papers: list[Paper] = []
    for entry_bib in sorted(_bib_dir(library).glob("*.bib")):
        try:
            paper = _paper(entry_bib)
        except StoreError:
            continue
        if wanted and wanted not in _split_keywords(paper["categories"]):
            continue
        papers.append(paper)
    return papers


def get_paper(key: str) -> Paper | None:
    return next((paper for paper in list_papers() if paper["key"] == key), None)


def paper_paths(paper: Paper) -> dict[str, str]:
    folder = Path(paper["folder"])
    pdf = _pdf_path(folder, paper["key"])
    return {
        "bib": str(_bib_path(folder, paper["key"])),
        "pdf": str(pdf) if pdf.is_file() else "",
    }


def resolve_paper(query: str) -> Paper:
    query = " ".join(query.split()).strip()
    if not query:
        raise StoreError("No query given.")
    lowered = query.lower()
    papers = list_papers()
    for paper in papers:
        if paper["key"] == lowered:
            return paper
    query_doi = _normalize_doi(query).lower()
    query_title = _normalized_title(query)
    substring_matches: list[Paper] = []
    for paper in papers:
        if query_doi and paper["doi"].lower() == query_doi:
            return paper
        if query_title and _normalized_title(paper["title"]) == query_title:
            return paper
        if lowered in paper["title"].lower() or lowered in paper["key"]:
            substring_matches.append(paper)
    if not substring_matches:
        raise StoreError(f"No paper matching '{query}'.")
    if len(substring_matches) > 1:
        listing = "\n".join(
            f"  {paper['key']} — {paper['title']}" for paper in substring_matches[:10]
        )
        extra = len(substring_matches) - 10
        suffix = f"\n  …and {extra} more" if extra > 0 else ""
        raise StoreError(
            f"'{query}' matches {len(substring_matches)} papers:\n{listing}{suffix}"
        )
    return substring_matches[0]


def _entry_and_bib(key: str) -> tuple[Path, Entry]:
    library = Path(load_config()["library"])
    direct = _bib_path(library, key)
    if direct.is_file():
        try:
            entry = _entries(direct.read_text(encoding="utf-8"))[0]
            if entry.key == key:
                return direct, entry
        except StoreError:
            pass
    for entry_bib, entry in _scan(library):
        if entry.key == key:
            return entry_bib, entry
    raise StoreError(f"No paper with key '{key}'.")


def categories(key: str) -> set[str]:
    _, entry = _entry_and_bib(key)
    return _keywords(entry)


def set_categories(key: str, value: set[str]) -> None:
    entry_bib, entry = _entry_and_bib(key)
    entry.fields = [field for field in entry.fields if field.key != "category"]
    if value:
        entry.set_field(Field("category", _keywords_text(value)))
    entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")


def search_index(category: str | None = None) -> list[str]:
    return [
        f"{paper['key']}\t{paper['year']} {paper['title']} — {paper['authors']}"
        for paper in list_papers(category)
    ]


def clean_library(keep_categories: set[str] | None = None) -> CleanReport:
    library = Path(load_config()["library"])
    keep = keep_categories if keep_categories is not None else {"dubois2026"}
    removed: list[tuple[str, str]] = []
    kept = 0
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    for entry_bib, entry in _scan(library):
        doi = _doi(entry)
        title = _normalized_title(_value(entry, "title"))
        duplicate_of = None
        if doi and doi in seen_dois:
            duplicate_of = "doi"
        elif title and title in seen_titles:
            duplicate_of = "title"
        if duplicate_of is not None:
            removed.append((entry_bib.stem, duplicate_of))
            entry_bib.unlink()
            _pdf_path(library, entry_bib.stem).unlink(missing_ok=True)
            continue
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.add(title)
        user_cats = _split_keywords(_value(entry, "keywords")) & keep
        entry.fields = [
            field for field in entry.fields if field.key not in ("keywords", "category")
        ]
        if user_cats:
            entry.set_field(Field("category", _keywords_text(user_cats)))
        entry.key = entry_bib.stem
        entry_bib.write_text(write_string(Library([entry])), encoding="utf-8")
        kept += 1
    return {"removed": removed, "kept": kept}


def resolve_paper_url(paper: Paper) -> str:
    if paper["url"]:
        return paper["url"]
    if paper["doi"]:
        return _doi_url(paper["doi"])
    raise StoreError(f"No URL available for '{paper['key']}'.")
