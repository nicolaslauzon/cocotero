import os
import tempfile
import time
from pathlib import Path

from rich.console import Console

from .config import config_dir, load_config
from .store import Paper, StoreError

console = Console()

_LOGIN_MARK = "/login?url="
_pw_error = None


def _playwright_error():
    global _pw_error
    if _pw_error is None:
        try:
            from playwright.sync_api import Error as PlaywrightError
        except ImportError:
            _pw_error = OSError
        else:
            _pw_error = PlaywrightError
    return _pw_error


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise StoreError(
            "Playwright is not installed. Run: uv add playwright && "
            "uv run playwright install chromium"
        )
    return sync_playwright()


def _profile_dir() -> Path:
    return config_dir() / "playwright_profile"


def _proxy_url(paper: Paper, cfg) -> str:
    landing = paper["url"] if paper["url"] else f"https://doi.org/{paper['doi']}"
    return f"{cfg['proxy_prefix']}{landing}"


def login() -> None:
    cfg = load_config()
    if not cfg["proxy_prefix"]:
        raise StoreError("Set proxy_prefix in your config first.")
    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    try:
        with _playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile), headless=False)
    except _playwright_error() as exc:
        raise StoreError(
            f"Could not launch Chromium: {exc}. Run: uv run playwright install chromium"
        ) from exc
    try:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(cfg["proxy_prefix"], wait_until="domcontentloaded")
        console.print(
            "[dim]Log in to EZproxy in the opened browser window, "
            "then close it when done.[/dim]"
        )
        while not context.is_closed():
            time.sleep(0.5)
        context.close()
    except _playwright_error() as exc:
        raise StoreError(f"EZproxy login failed: {exc}") from exc
    console.print("[green]EZproxy session saved for future downloads.[/green]")


def _pdf_href(page) -> str | None:
    for a in page.query_selector_all("a[href]"):
        href = a.get_attribute("href")
        if not href:
            continue
        low = href.lower()
        if any(hint in low for hint in ("/pdf", ".pdf", "stamp.jsp", "pdfft")):
            return page.urljoin(href)
    for a in page.query_selector_all("a[href]"):
        text = (a.inner_text() or "").lower()
        if "pdf" in text or "download" in text:
            href = a.get_attribute("href")
            if href:
                return page.urljoin(href)
    return None


def fetch_pdfs(papers: list[Paper]) -> dict[str, str | None]:
    cfg = load_config()
    results = {paper["key"]: None for paper in papers}
    if not cfg["proxy_prefix"]:
        return results
    profile = _profile_dir()
    if not (profile / "Default").is_dir():
        return results
    try:
        pw = _playwright()
    except StoreError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return results
    with pw:
        try:
            context = pw.chromium.launch_persistent_context(str(profile), headless=True)
        except _playwright_error() as exc:
            console.print(f"[yellow]Could not launch Chromium: {exc}[/yellow]")
            return results
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for paper in papers:
                try:
                    page.goto(
                        _proxy_url(paper, cfg),
                        wait_until="domcontentloaded",
                        timeout=45000,
                    )
                    if _LOGIN_MARK in page.url:
                        continue
                    href = _pdf_href(page)
                    if href:
                        response = context.request.get(href, timeout=60000)
                    else:
                        response = context.request.get(
                            page.url,
                            headers={"Accept": "application/pdf"},
                            timeout=60000,
                        )
                    if response.ok and response.body()[:4] == b"%PDF":
                        fd, name = tempfile.mkstemp(suffix=".pdf")
                        os.close(fd)
                        Path(name).write_bytes(response.body())
                        results[paper["key"]] = name
                except _playwright_error():
                    continue
                finally:
                    time.sleep(2.0)
            context.close()
        except _playwright_error():
            return results
    return results
