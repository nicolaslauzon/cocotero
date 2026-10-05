import argparse
import json
import re
import select
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console

from . import reading
from .citations import (
    CrossrefError,
    fetch_bibtex,
    fetch_bibtex_from_arxiv,
    search_by_title,
)
from .config import load_config
from .download import _should_handoff, download_pdf, handoff_paywalled
from .store import (
    StoreError,
    categories,
    clean_library,
    get_paper,
    link_pdf,
    list_papers,
    paper_from_result,
    paper_paths,
    resolve_paper,
    resolve_paper_url,
    search_index,
    set_categories,
    store_papers,
)
from .sync import drive_link, sync_library
from .ui import fzf_select, open_in_browser

console = Console()

PASTE_PROMPT = "Paste a DOI, arXiv link, title, or BibTeX, then press Enter:\n"
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s]+", re.IGNORECASE)
_ARXIV_RE = re.compile(
    r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}|[a-zA-Z.-]+/\d{7})",
    re.IGNORECASE,
)


def _read_paste() -> str:
    sys.stdout.write(PASTE_PROMPT)
    sys.stdout.flush()
    if not sys.stdin.isatty():
        return sys.stdin.read()
    first = _read_first_line()
    if not first.startswith("@"):
        return first
    return _drain_paste(first)


def _read_first_line() -> str:
    while True:
        try:
            line = input()
        except EOFError:
            return ""
        if line.strip():
            return line


def _drain_paste(first: str) -> str:
    parts = [first]
    depth = first.count("{") - first.count("}")
    while True:
        timeout = 2.0 if depth > 0 else 0.3
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
        except (OSError, ValueError):
            break
        if not ready:
            break
        chunk = sys.stdin.buffer.read1(65536)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        parts.append(text)
        depth += text.count("{") - text.count("}")
    return "\n".join(parts)


def _extract_doi(text: str) -> str | None:
    match = _DOI_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(".,;:)")


def _extract_arxiv(text: str) -> str | None:
    match = _ARXIV_RE.search(text)
    return match.group(1) if match else None


def _route_paste(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text.startswith("@"):
        return text
    if doi := _extract_doi(text):
        console.print(f"[dim]Detected DOI: {doi}[/dim]")
        return _lookup_by_doi(doi)
    if arxiv_id := _extract_arxiv(text):
        console.print(f"[dim]Detected arXiv: {arxiv_id}[/dim]")
        return _lookup_by_arxiv(arxiv_id)
    console.print("[dim]Detected title — searching Crossref…[/dim]")
    return _lookup_by_title(" ".join(text.split()))


def _lookup_by_title(title: str) -> str:
    try:
        hits = search_by_title(title)
    except CrossrefError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    if not hits:
        console.print(f"[red]No Crossref results for '{title}'.[/red]")
        raise SystemExit(1)
    lines = [
        f"{hit['doi']}\t{hit['year']} {hit['authors']} — {hit['title']}" for hit in hits
    ]
    selected = fzf_select(lines)
    if selected is None:
        return ""
    doi = selected.split("\t", maxsplit=1)[0]
    try:
        return fetch_bibtex(doi)
    except CrossrefError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def _lookup_by_doi(doi: str) -> str:
    try:
        return fetch_bibtex(doi)
    except CrossrefError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def _lookup_by_arxiv(arxiv_id: str) -> str:
    try:
        return fetch_bibtex_from_arxiv(arxiv_id)
    except CrossrefError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def _get_bibtex(args: argparse.Namespace) -> str:
    if args.bib:
        return args.bib
    if args.title:
        return _lookup_by_title(args.title)
    if args.doi:
        return _lookup_by_doi(args.doi)
    if args.text:
        return _route_paste(" ".join(args.text))
    return _route_paste(_read_paste())


def _download_for(results: list[dict], interactive: bool, handoff_mode: str) -> int:
    cfg = load_config()
    added = [
        paper_from_result(result)
        for result in results
        if result["status"] == "added" and not result["pdf"]
    ]
    pdf_count = 0
    if interactive:
        for paper in added:
            outcome = download_pdf(paper, interactive=True)
            if outcome["pdf"]:
                pdf_count += 1
                console.print(f"  [green]PDF[/green] via {outcome['source']}")
        return pdf_count
    paywalled: list = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download_pdf, paper): paper for paper in added}
        for future in as_completed(futures):
            paper = futures[future]
            outcome = future.result()
            if outcome["pdf"]:
                pdf_count += 1
                console.print(f"  [green]PDF[/green] via {outcome['source']}")
            else:
                paywalled.append(paper)
    paywalled = [paper for paper in paywalled if _should_handoff(paper, cfg)]
    if paywalled:
        console.print(f"[dim]Handing off {len(paywalled)} paywalled paper(s)…[/dim]")
        linked, failures = handoff_paywalled(paywalled, cfg, handoff_mode)
        pdf_count += linked
        _report_failures(failures)
    return pdf_count


def _report_failures(failures: dict[str, str]) -> None:
    if not failures:
        return
    console.print("[dim]Not fetched via EZproxy:[/dim]")
    for key, reason in failures.items():
        console.print(f"[dim]  {key} — {reason}[/dim]")


def _auto_sync() -> None:
    cfg = load_config()
    if not (cfg["auto_sync"] and cfg["drive_remote"]):
        return
    console.print("[dim]Syncing library to Drive…[/dim]")
    try:
        report = sync_library()
    except StoreError as exc:
        console.print(f"[yellow]Sync skipped: {exc}[/yellow]")
        return
    console.print(f"[dim]Synced: {report['linked']} PDF(s) on Drive.[/dim]")


def cmd_add(args: argparse.Namespace) -> None:
    bib_text = _get_bibtex(args).strip()
    if not bib_text:
        console.print("[red]No BibTeX received.[/red]")
        raise SystemExit(1)
    try:
        results = store_papers(bib_text, pdf_path=args.pdf)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    if not results:
        console.print("[red]No valid BibTeX entries found.[/red]")
        raise SystemExit(1)
    interactive = len(results) == 1
    handoff_mode = getattr(args, "handoff", None) or load_config()["handoff_mode"]
    for result in results:
        if result["status"] == "added":
            console.print(
                f"[green]Added[/green] [bold]{result['key']}[/bold] — {result['title']}"
            )
        else:
            console.print(
                f"[yellow]Skipped[/yellow] [bold]{result['key']}[/bold] — already in library"
            )
    pdf_count = 0 if args.no_pdf else _download_for(results, interactive, handoff_mode)
    if len(results) == 1 and results[0]["status"] == "added":
        result = results[0]
        pdf_file = Path(result["folder"]) / "pdf" / f"{result['key']}.pdf"
        console.print(f"  bib: {result['folder']}/bib/{result['key']}.bib")
        console.print(f"  pdf: {'stored' if pdf_file.is_file() else 'not stored'}")
    elif len(results) > 1:
        added = sum(1 for result in results if result["status"] == "added")
        skipped = len(results) - added
        console.print(
            f"[dim]Added {added}, skipped {skipped}, {pdf_count} PDF(s) downloaded.[/dim]"
        )
    if any(result["status"] == "added" for result in results):
        _auto_sync()


def cmd_cluster(args: argparse.Namespace) -> None:
    if args.text:
        bib_text = _route_paste(" ".join(args.text))
    else:
        bib_text = _route_paste(_read_paste())
    bib_text = bib_text.strip()
    if not bib_text:
        console.print("[red]No BibTeX received.[/red]")
        raise SystemExit(1)
    try:
        results = store_papers(bib_text)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    if not results:
        console.print("[red]No valid BibTeX entries found.[/red]")
        raise SystemExit(1)
    for result in results:
        set_categories(result["key"], categories(result["key"]) | {args.category})
    handoff_mode = getattr(args, "handoff", None) or load_config()["handoff_mode"]
    pdf_count = _download_for(results, interactive=False, handoff_mode=handoff_mode)
    for result in results:
        if result["status"] == "added":
            console.print(
                f"[green]Added[/green] [bold]{result['key']}[/bold] — {result['title']}"
            )
        else:
            console.print(
                f"[yellow]Already in library[/yellow] [bold]{result['key']}[/bold] — tagged"
            )
    console.print(
        f"[dim]Tagged {len(results)} paper(s) as '{args.category}', "
        f"{pdf_count} PDF(s) downloaded.[/dim]"
    )


def _retry_missing_pdfs(handoff_mode: str) -> None:
    missing = [paper for paper in list_papers() if not paper["has_pdf"]]
    if not missing:
        console.print("All papers have a PDF.")
        return
    console.print(f"Retrying {len(missing)} paper(s) without a PDF…")
    paywalled: list = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download_pdf, paper): paper for paper in missing}
        for future in as_completed(futures):
            paper = futures[future]
            outcome = future.result()
            if outcome["pdf"]:
                console.print(
                    f"[green]{paper['key']}[/green] — PDF via {outcome['source']}"
                )
            else:
                console.print(f"[dim]{paper['key']} — not found[/dim]")
                paywalled.append(paper)
    cfg = load_config()
    paywalled = [paper for paper in paywalled if _should_handoff(paper, cfg)]
    failures: dict[str, str] = {}
    if paywalled:
        console.print(f"[dim]Handing off {len(paywalled)} paywalled paper(s)…[/dim]")
        _, failures = handoff_paywalled(paywalled, cfg, handoff_mode)
    still_missing = [paper for paper in list_papers() if not paper["has_pdf"]]
    downloaded = len(missing) - len(still_missing)
    console.print(
        f"[dim]Done: {downloaded} PDF(s) downloaded, {len(still_missing)} still missing.[/dim]"
    )
    if failures:
        console.print("[dim]EZproxy failures:[/dim]")
        for key, reason in failures.items():
            console.print(f"[dim]  {key} — {reason}[/dim]")
    no_oa = [paper for paper in still_missing if paper["key"] not in failures]
    if no_oa:
        console.print(
            f"[dim]  …and {len(no_oa)} paper(s) with no open-access copy.[/dim]"
        )


def cmd_pdf(args: argparse.Namespace) -> None:
    try:
        cfg = load_config()
        handoff_mode = getattr(args, "handoff", None) or cfg["handoff_mode"]
        if args.path:
            stored = link_pdf(args.key, args.path)
            console.print(f"[green]Linked[/green] [bold]{args.key}[/bold] → {stored}")
            _auto_sync()
            return
        if args.key:
            paper = get_paper(args.key)
            if paper is None:
                console.print(f"[red]No paper with key '{args.key}'.[/red]")
                raise SystemExit(1)
            if paper["has_pdf"]:
                console.print(f"[yellow]{args.key}[/yellow] already has a PDF.")
                return
            outcome = download_pdf(paper, interactive=False)
            if outcome["pdf"]:
                console.print(
                    f"[green]{args.key}[/green] — PDF via {outcome['source']}"
                )
                _auto_sync()
                return
            if _should_handoff(paper, cfg):
                handoff_paywalled([paper], cfg, handoff_mode)
                return
            console.print(f"[yellow]{args.key}[/yellow] — not found (paywalled).")
            return
        _retry_missing_pdfs(handoff_mode)
        _auto_sync()
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def cmd_rm(args: argparse.Namespace) -> None:
    paper = get_paper(args.key)
    if paper is None:
        console.print(f"[red]No paper with key '{args.key}'.[/red]")
        raise SystemExit(1)
    library = Path(paper["folder"])
    (library / "bib" / f"{paper['key']}.bib").unlink(missing_ok=True)
    (library / "pdf" / f"{paper['key']}.pdf").unlink(missing_ok=True)
    console.print(f"[green]Removed[/green] [bold]{args.key}[/bold].")


def _open_paper_url(key: str) -> None:
    paper = get_paper(key)
    if paper is None:
        console.print(f"[red]No paper with key '{key}'.[/red]")
        raise SystemExit(1)
    if paper["has_pdf"]:
        pdf = Path(paper["folder"]) / "pdf" / f"{paper['key']}.pdf"
        console.print(f"Opening [cyan]{pdf}[/cyan]")
        open_in_browser(str(pdf))
        return
    try:
        url = resolve_paper_url(paper)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    console.print(f"Opening [cyan]{url}[/cyan]")
    open_in_browser(url)


def _fzf_pick_paper(category: str | None = None) -> str | None:
    lines = search_index(category=category)
    if not lines:
        if category:
            console.print(f"No papers in category '{category}'.")
        else:
            console.print("Library is empty. Add a paper with `cocotero add`.")
        raise SystemExit(1)
    library = Path(load_config()["library"])
    preview = (
        f'cat "{library}"/bib/{{1}}.bib; '
        f'echo; ls "{library}"/pdf/{{1}}.pdf 2>/dev/null || echo "PDF: none"'
    )
    selected = fzf_select(lines, preview_cmd=preview)
    if selected is None:
        return None
    return selected.split("\t", maxsplit=1)[0]


def cmd_open(args: argparse.Namespace) -> None:
    key = args.key or _fzf_pick_paper()
    if key is not None:
        _open_paper_url(key)


def cmd_browse_cluster(args: argparse.Namespace) -> None:
    key = _fzf_pick_paper(category=args.cluster)
    if key is not None:
        _open_paper_url(key)


def cmd_cite(args: argparse.Namespace) -> None:
    key = args.key or _fzf_pick_paper()
    if key is None:
        return
    paper = get_paper(key)
    if paper is None:
        console.print(f"[red]No paper with key '{key}'.[/red]")
        raise SystemExit(1)
    sys.stdout.write(
        (Path(paper["folder"]) / "bib" / f"{paper['key']}.bib").read_text(
            encoding="utf-8"
        )
    )


def cmd_read(args: argparse.Namespace) -> None:
    query = " ".join(args.query).strip()
    if not query:
        console.print("[red]Usage: cocotero read <key | doi | title>[/red]")
        raise SystemExit(1)
    try:
        paper = resolve_paper(query)
        paths = paper_paths(paper)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    if args.bibtex:
        sys.stdout.write(Path(paths["bib"]).read_text(encoding="utf-8"))
        return
    record = {
        **paper,
        "bib": paths["bib"],
        "pdf": paths["pdf"] or None,
        "drive": drive_link(paper) or None,
    }
    if args.json:
        json.dump(record, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    lines = [
        f"key: {record['key']}",
        f"title: {record['title']}",
        f"authors: {record['authors']}",
        f"year: {record['year']}",
        f"doi: {record['doi'] or 'none'}",
        f"url: {record['url'] or 'none'}",
        f"categories: {record['categories'] or 'none'}",
        f"arxiv: {record['arxiv'] or 'none'}",
        f"bib: {record['bib']}",
        f"pdf: {record['pdf'] or 'none'}",
        f"drive: {record['drive'] or 'none'}",
    ]
    sys.stdout.write("\n".join(lines) + "\n")


def cmd_sync(_args: argparse.Namespace) -> None:
    try:
        report = sync_library()
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    if report["pulled"]:
        console.print(f"Pulled {len(report['pulled'])} new paper(s).")
    for key in report["fetched"]:
        console.print(f"  [green]PDF[/green] {key}")
    if not report["uploaded"]:
        console.print(
            "[yellow]No drive_remote configured; Drive upload skipped.[/yellow]"
        )
    pushed = ", pushed" if report["pushed"] else ""
    console.print(
        f"[green]Synced[/green]: {report['linked']} PDF(s) on Drive, map.md updated{pushed}."
    )


def _reading_line(entry: reading.ReadingEntry) -> str:
    progress = f" ({entry['progress']})" if entry["progress"] else ""
    note = f" — {entry['note']}" if entry["note"] else ""
    return f"{entry['status']:<8} {entry['key']}{progress}: {entry['title']}{note}"


def _reading_record(entry: reading.ReadingEntry) -> dict[str, str]:
    paper = get_paper(entry["key"])
    if paper is None:
        return {**entry, "drive": "", "url": ""}
    try:
        url = resolve_paper_url(paper)
    except StoreError:
        url = ""
    return {**entry, "drive": drive_link(paper), "url": url}


def _reading_list(args: argparse.Namespace) -> None:
    items = reading.entries()
    if not args.all:
        items = [item for item in items if item["status"] in ("queued", "reading")]
    if args.json:
        json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    if not items:
        console.print("Reading list is empty.")
        return
    for item in reading.latest_first(items):
        console.print(
            _reading_line(item), markup=False, highlight=False, soft_wrap=True
        )


def _reading_current(args: argparse.Namespace) -> None:
    entry = reading.current()
    if entry is None:
        if args.json:
            sys.stdout.write("null\n")
        else:
            console.print("Nothing in progress.")
        return
    record = _reading_record(entry)
    if args.json:
        json.dump(record, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return
    console.print(_reading_line(entry), markup=False, highlight=False, soft_wrap=True)
    console.print(f"drive: {record['drive'] or 'none'}", markup=False)
    console.print(f"url: {record['url'] or 'none'}", markup=False)


def _reading_update(args: argparse.Namespace) -> None:
    paper = resolve_paper(" ".join(args.query))
    note = args.note or ""
    if args.action == "add":
        entry = reading.add(paper)
    elif args.action == "progress":
        entry = reading.set_progress(paper, args.where, note)
    elif args.action == "done":
        entry = reading.finish(paper, note)
    else:
        entry = reading.drop(paper, note)
    console.print(_reading_line(entry), markup=False, highlight=False, soft_wrap=True)


def cmd_reading(args: argparse.Namespace) -> None:
    action = args.action or "list"
    try:
        if action == "list":
            _reading_list(args)
        elif action == "current":
            _reading_current(args)
        else:
            _reading_update(args)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def cmd_clean(args: argparse.Namespace) -> None:
    keep = set(args.keep) or None
    try:
        report = clean_library(keep_categories=keep)
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    console.print(f"[green]Cleaned[/green] library: {report['kept']} papers kept.")
    for key, reason in report["removed"]:
        console.print(f"  [yellow]Removed[/yellow] {key} (duplicate by {reason})")


def cmd_login(_args: argparse.Namespace) -> None:
    try:
        from .ezproxy import login

        login()
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def _add_reading_parser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "reading", help="Reading list: queue papers and track progress."
    )
    parser.set_defaults(func=cmd_reading, action=None, all=False, json=False)
    actions = parser.add_subparsers(dest="action")
    list_parser = actions.add_parser("list", help="Show queued and in-progress papers.")
    list_parser.add_argument("--all", action="store_true", help="Include done/dropped.")
    list_parser.add_argument("--json", action="store_true")
    current = actions.add_parser(
        "current", help="The paper read most recently that is not finished."
    )
    current.add_argument("--json", action="store_true")
    for name, help_text in [
        ("add", "Queue a paper."),
        ("progress", "Record how far you are, e.g. p12/30 or 40%%."),
        ("done", "Mark a paper as finished."),
        ("drop", "Stop reading a paper."),
    ]:
        action = actions.add_parser(name, help=help_text)
        action.add_argument("query", nargs="+", help="Key, DOI, or title fragment.")
        if name == "progress":
            action.add_argument("--at", dest="where", required=True)
        action.add_argument("--note", help="Free-form note (e.g. your impressions).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocotero", description="CLI paper manager.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser(
        "add", help="Add one or many papers: paste a DOI, arXiv link, title, or BibTeX."
    )
    add.add_argument(
        "text",
        nargs="*",
        help="DOI, arXiv link, title, or BibTeX (auto-detected; no quotes needed).",
    )
    add.add_argument(
        "-b", "--bib", help="Raw BibTeX text (instead of interactive paste)."
    )
    add.add_argument("--pdf", help="Path to a PDF to store alongside the entry.")
    add.add_argument(
        "-t", "--title", help="Article title (Crossref lookup + fzf pick)."
    )
    add.add_argument("-d", "--doi", help="DOI (Crossref BibTeX lookup).")
    add.add_argument(
        "--no-pdf",
        action="store_true",
        help="Store the BibTeX only; skip PDF downloads (e.g. in the cloud).",
    )
    add.add_argument(
        "--handoff",
        choices=["assisted", "auto"],
        help="Paywalled-paper strategy (default: config 'handoff_mode').",
    )
    add.set_defaults(func=cmd_add)

    open_parser = sub.add_parser(
        "open", help="Open a paper in your browser. Without a key, pick via fzf."
    )
    open_parser.add_argument("key", nargs="?")
    open_parser.set_defaults(func=cmd_open)

    browse_parser = sub.add_parser(
        "browse-cluster",
        help="Fuzzy-pick and open a paper within one cluster (category).",
    )
    browse_parser.add_argument("cluster")
    browse_parser.set_defaults(func=cmd_browse_cluster)

    cite_parser = sub.add_parser(
        "cite", help="Print the stored BibTeX entry for a paper."
    )
    cite_parser.add_argument("key", nargs="?")
    cite_parser.set_defaults(func=cmd_cite)

    read_parser = sub.add_parser(
        "read",
        help="Non-interactive lookup: metadata plus absolute bib/pdf paths.",
    )
    read_parser.add_argument(
        "query", nargs="*", help="Key, DOI, arXiv ID, or title fragment."
    )
    read_parser.add_argument(
        "--json", action="store_true", help="Print the full record as JSON."
    )
    read_parser.add_argument(
        "--bibtex", action="store_true", help="Print the stored BibTeX entry instead."
    )
    read_parser.set_defaults(func=cmd_read)

    cluster_parser = sub.add_parser(
        "cluster",
        help="Add a pasted bibliography and tag every paper with one category.",
    )
    cluster_parser.add_argument("category")
    cluster_parser.add_argument("text", nargs="*")
    cluster_parser.add_argument(
        "--handoff",
        choices=["assisted", "auto"],
        help="Paywalled-paper strategy (default: config 'handoff_mode').",
    )
    cluster_parser.set_defaults(func=cmd_cluster)

    pdf_parser = sub.add_parser(
        "pdf", help="Retry PDF downloads, or link a local PDF file."
    )
    pdf_parser.add_argument(
        "key", nargs="?", help="Retry this paper (omit to retry all missing)."
    )
    pdf_parser.add_argument(
        "path", nargs="?", help="Local PDF file to link to the given key."
    )
    pdf_parser.add_argument(
        "--handoff",
        choices=["assisted", "auto"],
        help="Paywalled-paper strategy (default: config 'handoff_mode').",
    )
    pdf_parser.set_defaults(func=cmd_pdf)

    rm_parser = sub.add_parser("rm", help="Remove a paper from the library.")
    rm_parser.add_argument("key")
    rm_parser.set_defaults(func=cmd_rm)

    clean_parser = sub.add_parser(
        "clean",
        help="Deduplicate the library and keep only user categories.",
    )
    clean_parser.add_argument(
        "--keep",
        action="append",
        default=[],
        help="User categories to preserve (repeatable; default: dubois2026).",
    )
    clean_parser.set_defaults(func=cmd_clean)

    sub.add_parser(
        "sync",
        help="Pull the library repo, mirror PDFs to Google Drive, refresh map.md, push.",
    ).set_defaults(func=cmd_sync)

    _add_reading_parser(sub)

    sub.add_parser(
        "login", help="Save an EZproxy session for auto PDF downloads."
    ).set_defaults(func=cmd_login)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
