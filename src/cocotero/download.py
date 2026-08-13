import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

import requests
from rich.console import Console

from .config import Config, load_config, user_agent
from .store import Paper, StoreError, link_pdf
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
    "10.1145",
    "10.1038",
    "10.1021",
    "10.1111",
    "10.1126",
)


def _try_semanticscholar(paper: Paper, _cfg: Config) -> str | None:
    response = requests.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": paper["title"], "fields": "openAccessPdf,externalIds"},
        headers=user_agent(),
        timeout=15,
    )
    response.raise_for_status()
    for item in response.json().get("data", []):
        open_pdf = item.get("openAccessPdf")
        if open_pdf and open_pdf.get("url"):
            return open_pdf["url"]
    return None


def _try_unpaywall(paper: Paper, cfg: Config) -> str | None:
    if not paper["doi"] or not cfg["unpaywall_email"]:
        return None
    response = requests.get(
        f"https://api.unpaywall.org/v2/{paper['doi']}",
        params={"email": cfg["unpaywall_email"]},
        headers=user_agent(),
        timeout=15,
    )
    response.raise_for_status()
    location = response.json().get("best_oa_location")
    if location and location.get("url_for_pdf"):
        return location["url_for_pdf"]
    return None


def _arxiv_id_from_url(url: str) -> str | None:
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/\s]+)", url)
    return match.group(1) if match else None


def _arxiv_id_from_title(title: str) -> str | None:
    response = requests.get(
        _ARXIV_API,
        params={"search_query": f'ti:"{title}"', "max_results": 1},
        headers=user_agent(),
        timeout=15,
    )
    response.raise_for_status()
    entry = ET.fromstring(response.text).find("a:entry", _ATOM_NS)
    if entry is None:
        return None
    return entry.findtext("a:id", "", _ATOM_NS).rsplit("/", 1)[-1]


def _try_arxiv(paper: Paper, _cfg: Config) -> str | None:
    arxiv_id = _arxiv_id_from_url(paper["url"]) or _arxiv_id_from_title(paper["title"])
    if not arxiv_id:
        return None
    return f"https://arxiv.org/pdf/{arxiv_id}"


_SOURCES: dict[str, Callable[[Paper, Config], str | None]] = {
    "semanticscholar": _try_semanticscholar,
    "unpaywall": _try_unpaywall,
    "arxiv": _try_arxiv,
}


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
        "[dim]Paywalled — opening your university proxy page in your browser…[/dim]"
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


def download_pdf(paper: Paper, interactive: bool = False) -> DownloadResult:
    cfg = load_config()
    for source in cfg["pdf_priority"]:
        fetcher = _SOURCES.get(source)
        if fetcher is None:
            continue
        try:
            url = fetcher(paper, cfg)
        except (requests.RequestException, ValueError, ET.ParseError, KeyError):
            continue
        if not url:
            continue
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
