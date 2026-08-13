import os
import re
import tempfile
import time
from pathlib import Path

from rich.console import Console
from rich.progress import Progress

from .config import config_dir, load_config
from .store import Paper, StoreError

console = Console()

_LOGIN_MARK = "/login?url="
_IEEE_DOC_RE = re.compile(r"ieeexplore[^/]*/document/(\d+)", re.IGNORECASE)
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
            "Playwright is not installed. Reinstall cocotero with `--with playwright` "
            "(see README → Install → EZproxy support)."
        )
    return sync_playwright()


def _profile_dir() -> Path:
    return config_dir() / "playwright_profile"


def _proxy_url(paper: Paper, cfg) -> str:
    landing = paper["url"] if paper["url"] else f"https://doi.org/{paper['doi']}"
    return f"{cfg['proxy_prefix']}{landing}"


def _libkey_base_url(cfg) -> str:
    lib_id = str(cfg["libkey_library_id"]).strip("/")
    return f"https://libkey.io/libraries/{lib_id}" if lib_id else "https://libkey.io"


def _libkey_url(paper: Paper, cfg) -> str:
    return f"{_libkey_base_url(cfg)}/{paper['doi']}"


def _wait_for_user(context) -> None:
    try:
        input()
    except EOFError:
        deadline = time.monotonic() + 600
        while not context.is_closed() and context.pages and time.monotonic() < deadline:
            time.sleep(1)
        if time.monotonic() >= deadline:
            raise StoreError(
                "Timed out after 10 minutes waiting for you to close the browser window."
            )


def login() -> None:
    cfg = load_config()
    if not cfg["proxy_prefix"]:
        raise StoreError("Set proxy_prefix in your config first.")
    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    try:
        with _playwright() as p:
            context = p.chromium.launch_persistent_context(str(profile), headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(cfg["proxy_prefix"], wait_until="domcontentloaded")
                console.print(
                    "[dim]Sign in to EZproxy in the browser window, "
                    "then press Enter here when done.[/dim]"
                )
                _wait_for_user(context)
                if not context.is_closed() and cfg["libkey_library_id"]:
                    page.goto(_libkey_base_url(cfg), wait_until="domcontentloaded")
                    console.print(
                        "[dim]Pick your organization on libkey.io and check "
                        "'Download PDF', then press Enter here when done.[/dim]"
                    )
                    _wait_for_user(context)
                if not context.is_closed():
                    context.close()
            except _playwright_error() as exc:
                raise StoreError(f"EZproxy login failed: {exc}") from exc
    except _playwright_error() as exc:
        raise StoreError(
            f"Could not launch Chromium: {exc}. Run: "
            "~/.local/share/uv/tools/cocotero/bin/python -m playwright install chromium"
        ) from exc
    except KeyboardInterrupt:
        console.print("\n[yellow]Login cancelled.[/yellow]")
        return
    console.print("[green]EZproxy session saved for future downloads.[/green]")


def _pdf_href(page) -> str | None:
    from urllib.parse import urljoin

    for a in page.query_selector_all("a[href]"):
        href = a.get_attribute("href")
        if not href:
            continue
        low = href.lower()
        if any(hint in low for hint in ("/pdf", ".pdf", "stamp.jsp", "pdfft")):
            return urljoin(page.url, href)
    for a in page.query_selector_all("a[href]"):
        text = (a.inner_text() or "").lower()
        if "pdf" in text or "download" in text:
            href = a.get_attribute("href")
            if href:
                return urljoin(page.url, href)
    return None


def _ieee_stamp_url(page_url: str) -> str | None:
    match = _IEEE_DOC_RE.search(page_url)
    if not match:
        return None
    from urllib.parse import urlparse

    origin = urlparse(page_url)
    return (
        f"{origin.scheme}://{origin.netloc}/stamp/stamp.jsp"
        f"?tp=&arnumber={match.group(1)}"
    )


def _grab_pdf(page, context) -> tuple[str | None, str | None]:
    href = _pdf_href(page) or _ieee_stamp_url(page.url)
    if href:
        response = context.request.get(href, timeout=60000)
    else:
        response = context.request.get(
            page.url,
            headers={"Accept": "application/pdf"},
            timeout=60000,
        )
    if not response.ok:
        return None, f"HTTP {response.status}"
    if response.body()[:4] != b"%PDF":
        return None, "not a PDF"
    fd, name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    Path(name).write_bytes(response.body())
    return name, None


def _fetch_paper_pdf(page, context, paper: Paper, cfg) -> tuple[str | None, str | None]:
    page.goto(_proxy_url(paper, cfg), wait_until="domcontentloaded", timeout=45000)
    if _LOGIN_MARK in page.url:
        return None, "session expired"
    return _grab_pdf(page, context)


def _libkey_pdf(page, context, paper: Paper, cfg) -> tuple[str | None, str | None]:
    page.goto(_libkey_url(paper, cfg), wait_until="domcontentloaded", timeout=45000)
    if _LOGIN_MARK in page.url:
        return None, "session expired"
    return _grab_pdf(page, context)


def fetch_pdfs(
    papers: list[Paper],
) -> tuple[dict[str, str | None], dict[str, str]]:
    cfg = load_config()
    results = {paper["key"]: None for paper in papers}
    if not cfg["proxy_prefix"]:
        return results, {}
    profile = _profile_dir()
    if not (profile / "Default").is_dir():
        return results, {}
    try:
        pw = _playwright()
    except StoreError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        return results, {}
    with pw as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile), headless=True
            )
        except _playwright_error() as exc:
            console.print(f"[yellow]Could not launch Chromium: {exc}[/yellow]")
            return results, {}
        login_hits = 0
        reasons: dict[str, str] = {}
        try:
            page = context.pages[0] if context.pages else context.new_page()
            with Progress(console=console) as progress:
                task = progress.add_task(
                    "Fetching paywalled PDFs via EZproxy", total=len(papers)
                )
                for paper in papers:
                    try:
                        progress.update(task, description=f"Fetching {paper['key']}")
                        temp, reason = _libkey_pdf(page, context, paper, cfg)
                        if temp is None:
                            temp, reason = _fetch_paper_pdf(page, context, paper, cfg)
                    except _playwright_error() as exc:
                        name = type(exc).__name__
                        temp, reason = (
                            None,
                            "timed out" if name == "TimeoutError" else name,
                        )
                    finally:
                        time.sleep(2.0)
                        progress.advance(task)
                    if temp:
                        results[paper["key"]] = temp
                    elif reason:
                        if reason == "session expired":
                            login_hits += 1
                        reasons[paper["key"]] = reason
            context.close()
        except _playwright_error():
            return results, reasons
    if login_hits and not any(results.values()):
        console.print(
            "[yellow]EZproxy session may have expired — run `cocotero login`.[/yellow]"
        )
    return results, reasons
