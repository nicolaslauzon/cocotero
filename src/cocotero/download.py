import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypedDict

import requests
from rich.console import Console
from rich.progress import Progress

from .config import Config, load_config, user_agent
from .store import (
    Paper,
    StoreError,
    _normalized_title,
    link_pdf,
    set_doi,
)
from .ui import fzf_select, open_in_browser

console = Console()


class DownloadResult(TypedDict):
    source: str | None
    pdf: str | None


_ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}
_ARXIV_API = "https://export.arxiv.org/api/query"
_INSTITUTIONAL_PREFIXES = (
    "10.1109",
    "10.1016",
    "10.1007",
    "10.1002",
    "10.1145",
    "10.1038",
    "10.1021",
    "10.1111",
    "10.1126",
)


def _try_semanticscholar(paper: Paper, _cfg: Config) -> str | None:
    if paper["doi"]:
        try:
            response = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/DOI:{paper['doi']}",
                params={"fields": "openAccessPdf"},
                headers=user_agent(),
                timeout=10,
            )
            response.raise_for_status()
            location = response.json().get("openAccessPdf")
            if location and location.get("url"):
                return location["url"]
        except (requests.RequestException, ValueError, KeyError):
            pass
    try:
        response = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": paper["title"], "fields": "openAccessPdf"},
            headers=user_agent(),
            timeout=10,
        )
        response.raise_for_status()
        for item in response.json().get("data", []):
            location = item.get("openAccessPdf")
            if location and location.get("url"):
                return location["url"]
    except (requests.RequestException, ValueError, KeyError):
        pass
    return None


def _landing_to_pdf(url: str) -> str | None:
    if not url:
        return None
    arxiv = re.search(r"arxiv\.org/(?:abs|pdf)/([^/\s]+)", url)
    if arxiv:
        return f"https://arxiv.org/pdf/{arxiv.group(1)}"
    if "mdpi.com" in url:
        base = url.rstrip("/")
        return base if base.endswith("/pdf") else f"{base}/pdf"
    return url


def _try_unpaywall(paper: Paper, cfg: Config) -> str | None:
    if not paper["doi"] or not cfg["unpaywall_email"]:
        return None
    try:
        response = requests.get(
            f"https://api.unpaywall.org/v2/{paper['doi']}",
            params={"email": cfg["unpaywall_email"]},
            headers=user_agent(),
            timeout=10,
        )
        response.raise_for_status()
    except (requests.RequestException, ValueError):
        return None
    payload = response.json()
    locations = []
    if payload.get("best_oa_location"):
        locations.append(payload["best_oa_location"])
    locations.extend(payload.get("oa_locations") or [])
    for location in locations:
        pdf_url = location.get("url_for_pdf") if location else None
        if pdf_url:
            return pdf_url
    for location in locations:
        if not location:
            continue
        landing = location.get("url_for_landing_page") or location.get("url")
        converted = _landing_to_pdf(landing)
        if converted:
            return converted
    return None


def _try_crossref(paper: Paper, cfg: Config) -> str | None:
    if not paper["doi"]:
        return None
    try:
        response = requests.get(
            f"https://api.crossref.org/works/{paper['doi']}",
            params={"mailto": cfg["unpaywall_email"]} if cfg["unpaywall_email"] else {},
            headers=user_agent(),
            timeout=10,
        )
        response.raise_for_status()
    except (requests.RequestException, ValueError):
        return None
    links = (response.json().get("message") or {}).get("link") or []
    for link in links:
        if link.get("content-type") == "application/pdf" and link.get("URL"):
            return link["URL"]
    for link in links:
        url = link.get("URL")
        if url and re.search(r"\.pdf(\?|$)", url, re.IGNORECASE):
            return url
    return None


def _arxiv_id_from_url(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/\s]+)", url)
    return match.group(1) if match else None


def _arxiv_id_from_title(title: str) -> str | None:
    response = requests.get(
        _ARXIV_API,
        params={"search_query": f'ti:"{title}"', "max_results": 1},
        headers=user_agent(),
        timeout=10,
    )
    response.raise_for_status()
    entry = ET.fromstring(response.text).find("a:entry", _ATOM_NS)
    if entry is None:
        return None
    return entry.findtext("a:id", "", _ATOM_NS).rsplit("/", 1)[-1]


def _try_arxiv(paper: Paper, _cfg: Config) -> str | None:
    arxiv_id = _arxiv_id_from_url(paper["url"])
    if not arxiv_id:
        try:
            arxiv_id = _arxiv_id_from_title(paper["title"])
        except (requests.RequestException, ET.ParseError):
            return None
    if not arxiv_id:
        return None
    return f"https://arxiv.org/pdf/{arxiv_id}"


_SOURCES: dict[str, Callable[[Paper, Config], str | None]] = {
    "semanticscholar": _try_semanticscholar,
    "unpaywall": _try_unpaywall,
    "crossref": _try_crossref,
    "arxiv": _try_arxiv,
}


def _discover_urls(paper: Paper, cfg: Config) -> list[tuple[str, str]]:
    fetchers = [
        (name, _SOURCES[name]) for name in cfg["pdf_priority"] if name in _SOURCES
    ]
    if not fetchers:
        return []
    found: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as pool:
        futures = {pool.submit(fetch, paper, cfg): name for name, fetch in fetchers}
        for future in as_completed(futures):
            name = futures[future]
            try:
                url = future.result()
            except requests.RequestException:
                continue
            if url:
                found[name] = url
    return [(name, found[name]) for name in cfg["pdf_priority"] if name in found]


def _fetch_pdf(url: str) -> Path | None:
    response = requests.get(url, headers=user_agent(), timeout=60, stream=True)
    response.raise_for_status()
    fd, name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    target = Path(name)
    with target.open("wb") as fh:
        for chunk in response.iter_content(65536):
            fh.write(chunk)
    if target.read_bytes()[:4] != b"%PDF":
        target.unlink(missing_ok=True)
        return None
    return target


def _should_handoff(paper: Paper, cfg: Config) -> bool:
    return bool(cfg["proxy_prefix"]) and paper["doi"].startswith(
        _INSTITUTIONAL_PREFIXES
    )


def _ezproxy_handoff(paper: Paper, cfg: Config) -> str | None:
    downloads = Path(cfg["downloads_dir"]).expanduser()
    baseline = (
        {path for path in downloads.glob("*.pdf")} if downloads.is_dir() else set()
    )
    landing = paper["url"] if paper["url"] else f"https://doi.org/{paper['doi']}"
    console.print(
        f"[dim]Paywalled — opening your university proxy page for {paper['key']}…[/dim]"
    )
    open_in_browser(f"{cfg['proxy_prefix']}{landing}")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(2)
        current = (
            {path for path in downloads.glob("*.pdf")} if downloads.is_dir() else set()
        )
        new_files = current - baseline
        if not new_files:
            continue
        if len(new_files) == 1:
            return link_pdf(paper["key"], str(new_files.pop()))
        selected = fzf_select([str(path) for path in sorted(new_files)])
        if selected:
            return link_pdf(paper["key"], selected)
    return None


def handoff_paywalled(
    papers: list[Paper], cfg: Config, mode: str
) -> tuple[int, dict[str, str]]:
    linked = 0
    failures: dict[str, str] = {}
    if mode == "auto":
        from . import ezproxy

        results, reasons = ezproxy.fetch_pdfs(papers)
        for paper in papers:
            temp = results.get(paper["key"])
            if not temp:
                continue
            try:
                link_pdf(paper["key"], temp)
                linked += 1
                console.print(f"[green]{paper['key']}[/green] — PDF via ezproxy")
            except StoreError:
                pass
            finally:
                Path(temp).unlink(missing_ok=True)
        failures = {
            key: reason for key, reason in reasons.items() if not results.get(key)
        }
        return linked, failures
    with Progress(console=console) as progress:
        task = progress.add_task("Handing off paywalled papers", total=len(papers))
        for paper in papers:
            try:
                stored = _ezproxy_handoff(paper, cfg)
            except (StoreError, OSError) as exc:
                failures[paper["key"]] = type(exc).__name__
                stored = None
            if stored:
                linked += 1
                console.print(f"[green]{paper['key']}[/green] — PDF via ezproxy")
            else:
                failures.setdefault(paper["key"], "no download detected")
            progress.advance(task)
    return linked, failures


def _resolve_doi_by_title(paper: Paper) -> str | None:
    title = paper["title"].strip()
    if not title:
        return None
    try:
        response = requests.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": title, "rows": 5},
            headers=user_agent(),
            timeout=15,
        )
        response.raise_for_status()
        items = response.json()["message"]["items"]
    except (requests.RequestException, KeyError, ValueError):
        return None
    normalized = _normalized_title(title)
    for item in items:
        candidates = item.get("title") or []
        if not candidates:
            continue
        if _normalized_title(str(candidates[0])) == normalized:
            return str(item.get("DOI", ""))
    return None


def download_pdf(paper: Paper, interactive: bool = False) -> DownloadResult:
    cfg = load_config()
    if not paper["doi"]:
        resolved = _resolve_doi_by_title(paper)
        if resolved:
            paper["doi"] = resolved
            try:
                set_doi(paper["key"], resolved)
            except StoreError:
                pass
    for source, url in _discover_urls(paper, cfg):
        temp: Path | None = None
        try:
            temp = _fetch_pdf(url)
            if temp is None:
                continue
            stored = link_pdf(paper["key"], str(temp))
        except (requests.RequestException, OSError, StoreError):
            continue
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return {"source": source, "pdf": stored}
    if interactive and _should_handoff(paper, cfg):
        stored = _ezproxy_handoff(paper, cfg)
        if stored:
            return {"source": "ezproxy", "pdf": stored}
    return {"source": None, "pdf": None}
