import xml.etree.ElementTree as ET
from typing import TypedDict

import requests

from .config import user_agent


class CrossrefError(Exception):
    pass


class CrossrefHit(TypedDict):
    doi: str
    title: str
    authors: str
    year: str


_API = "https://api.crossref.org/works"
_ARXIV_API = "https://export.arxiv.org/api/query"
_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}


def _first_author(authors: list[object]) -> str:
    names = []
    for author in authors[:3]:
        if not isinstance(author, dict):
            continue
        family = str(author.get("family", ""))
        given = str(author.get("given", ""))
        names.append(f"{family}, {given}" if family else given)
    return " and ".join(names)


def _year(issued: object) -> str:
    if not isinstance(issued, dict):
        return ""
    parts = issued.get("date-parts", [])
    if parts and isinstance(parts[0], list) and parts[0]:
        return str(parts[0][0])
    return ""


def _to_hit(item: dict[str, object]) -> CrossrefHit:
    title = str(item.get("title", [""])[0] if isinstance(item.get("title"), list) else item.get("title", ""))
    return {
        "doi": str(item.get("DOI", "")),
        "title": title,
        "authors": _first_author(item.get("author", []) if isinstance(item.get("author"), list) else []),
        "year": _year(item.get("issued")),
    }


def search_by_title(title: str) -> list[CrossrefHit]:
    params = {"query.bibliographic": title, "rows": 8}
    try:
        response = requests.get(_API, params=params, headers=user_agent(), timeout=15)
        response.raise_for_status()
        items = response.json()["message"]["items"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise CrossrefError(f"Crossref search failed: {exc}") from exc
    return [_to_hit(item) for item in items]


def fetch_bibtex(doi: str) -> str:
    headers = {**user_agent(), "Accept": "application/x-bibtex"}
    try:
        response = requests.get(f"https://doi.org/{doi}", headers=headers, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CrossrefError(f"Crossref BibTeX fetch failed for {doi}: {exc}") from exc
    if not response.text.strip():
        raise CrossrefError(f"No BibTeX returned for DOI {doi}.")
    return response.text.strip()


def fetch_bibtex_from_arxiv(arxiv_id: str) -> str:
    try:
        response = requests.get(_ARXIV_API, params={"id_list": arxiv_id}, headers=user_agent(), timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise CrossrefError(f"arXiv fetch failed for {arxiv_id}: {exc}") from exc
    try:
        entry = ET.fromstring(response.text).find("a:entry", _ATOM_NS)
    except ET.ParseError as exc:
        raise CrossrefError(f"Could not parse arXiv response for {arxiv_id}.") from exc
    if entry is None:
        raise CrossrefError(f"No arXiv entry for ID {arxiv_id}.")
    title = " ".join(entry.findtext("a:title", "", _ATOM_NS).split())
    authors = " and ".join(
        author.findtext("a:name", "", _ATOM_NS)
        for author in entry.findall("a:author", _ATOM_NS)
    )
    published = entry.findtext("a:published", "", _ATOM_NS)
    year = published[:4] if len(published) >= 4 else ""
    url = f"https://arxiv.org/abs/{arxiv_id}"
    return (
        f"@misc{{{arxiv_id},\n"
        f"  title = {{{title}}},\n"
        f"  author = {{{authors}}},\n"
        f"  year = {{{year}}},\n"
        f"  url = {{{url}}},\n"
        f"  eprint = {{{arxiv_id}}},\n"
        f"  archiveprefix = {{arXiv}}\n"
        f"}}"
    )