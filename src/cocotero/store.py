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


def _doi(entry: Entry) -> str:
    return _value(entry, "doi").strip().lower()


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


@dataclass
class LibraryIndex:
    by_doi: dict[str, Path]
    by_title: dict[str, Path]


def _build_index(library: Path) -> LibraryIndex:
    by_doi: dict[str, Path] = {}
    by_title: dict[str, Path] = {}
    for folder, entry in _scan(library):
        doi = _doi(entry)
        if doi:
            by_doi.setdefault(doi, folder)
        title = _normalized_title(_value(entry, "title"))
        if title:
            by_title.setdefault(title, folder)
    return LibraryIndex(by_doi=by_doi, by_title=by_title)


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
    folder = library / key
    folder.mkdir(parents=True, exist_ok=False)

    entry.key = key
    if doi and not entry.get("url"):
        entry.set_field(Field("url", _doi_url(doi)))
    (folder / "entry.bib").write_text(write_string(Library([entry])), encoding="utf-8")

    stored_pdf = link_pdf(key, pdf_path) if pdf_path else None

    if doi:
        index.by_doi[doi] = folder
    if title:
        index.by_title[title] = folder

    return {
        "key": key,
        "title": _value(entry, "title"),
        "folder": str(folder),
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
    folder, entry = _entry_and_folder(key)
    src = Path(pdf_path).expanduser()
    if not src.is_file():
        raise StoreError(f"PDF not found: {src}")
    shutil.copy2(src, folder / "paper.pdf")
    if not entry.get("file"):
        entry.set_field(Field("file", ":paper.pdf:PDF"))
    (folder / "entry.bib").write_text(write_string(Library([entry])), encoding="utf-8")
    return str(folder / "paper.pdf")


def _paper(entry_bib: Path) -> Paper:
    entry = _entries(entry_bib.read_text(encoding="utf-8"))[0]
    return {
        "key": entry.key,
        "year": _value(entry, "year"),
        "authors": _value(entry, "author"),
        "title": _value(entry, "title"),
        "url": _value(entry, "url"),
        "doi": _value(entry, "doi"),
        "has_pdf": (entry_bib.parent / "paper.pdf").is_file(),
        "folder": str(entry_bib.parent),
        "categories": _value(entry, "category"),
    }


def paper_from_result(result: StoredPaper) -> Paper:
    return _paper(Path(result["folder"]) / "entry.bib")


def list_papers(category: str | None = None) -> list[Paper]:
    library = Path(load_config()["library"])
    normalize_library()
    wanted = category.lower() if category else None
    papers: list[Paper] = []
    for entry_bib in sorted(library.glob("*/entry.bib")):
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


def _entry_and_folder(key: str) -> tuple[Path, Entry]:
    library = Path(load_config()["library"])
    direct = library / key
    if (direct / "entry.bib").is_file():
        try:
            entry = _entries((direct / "entry.bib").read_text(encoding="utf-8"))[0]
            if entry.key == key:
                return direct, entry
        except StoreError:
            pass
    for folder, entry in _scan(library):
        if entry.key == key:
            return folder, entry
    raise StoreError(f"No paper with key '{key}'.")


def categories(key: str) -> set[str]:
    _, entry = _entry_and_folder(key)
    return _keywords(entry)


def set_categories(key: str, value: set[str]) -> None:
    folder, entry = _entry_and_folder(key)
    entry.fields = [field for field in entry.fields if field.key != "category"]
    if value:
        entry.set_field(Field("category", _keywords_text(value)))
    (folder / "entry.bib").write_text(write_string(Library([entry])), encoding="utf-8")


def toggle_category(key: str, category: str) -> bool:
    current = categories(key)
    if category in current:
        set_categories(key, current - {category})
        return False
    set_categories(key, current | {category})
    return True


def list_categories() -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for paper in list_papers():
        for category in _split_keywords(paper["categories"]):
            counts[category] = counts.get(category, 0) + 1
    return sorted(counts.items())


def clean_library(keep_categories: set[str] | None = None) -> CleanReport:
    library = Path(load_config()["library"])
    keep = keep_categories if keep_categories is not None else {"dubois2026"}
    removed: list[tuple[str, str]] = []
    kept = 0
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    for folder, entry in sorted(_scan(library), key=lambda item: item[0].name):
        doi = _doi(entry)
        title = _normalized_title(_value(entry, "title"))
        duplicate_of = None
        if doi and doi in seen_dois:
            duplicate_of = "doi"
        elif title and title in seen_titles:
            duplicate_of = "title"
        if duplicate_of is not None:
            removed.append((folder.name, duplicate_of))
            shutil.rmtree(folder)
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
        entry.key = folder.name
        (folder / "entry.bib").write_text(
            write_string(Library([entry])), encoding="utf-8"
        )
        kept += 1
    return {"removed": removed, "kept": kept}


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
