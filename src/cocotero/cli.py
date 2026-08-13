import argparse
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .citations import (
    CrossrefError,
    fetch_bibtex,
    fetch_bibtex_from_arxiv,
    search_by_title,
)
from .config import load_config
from .download import download_pdf
from .store import (
    StoreError,
    get_paper,
    keywords,
    link_pdf,
    list_categories,
    list_papers,
    resolve_paper_url,
    search_index,
    set_keywords,
    store_papers,
    toggle_keyword,
)
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
    try:
        lines = [input()]
    except EOFError:
        return ""
    if not lines[0].startswith("@"):
        return lines[0]
    while not lines[-1].rstrip().endswith("}"):
        try:
            lines.append(input())
        except EOFError:
            break
    return "\n".join(lines)


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
    interactive = len(results) == 1
    pdf_count = 0
    for result in results:
        if result["status"] == "added":
            console.print(
                f"[green]Added[/green] [bold]{result['key']}[/bold] — {result['title']}"
            )
        else:
            console.print(
                f"[yellow]Skipped[/yellow] [bold]{result['key']}[/bold] — already in library"
            )
        if result["status"] == "added" and not result["pdf"]:
            paper = get_paper(result["key"])
            if paper is not None:
                outcome = download_pdf(paper, interactive=interactive)
                if outcome["pdf"]:
                    pdf_count += 1
                    console.print(f"  [green]PDF[/green] via {outcome['source']}")
                elif interactive:
                    console.print("  [yellow]PDF: not found (paywalled).[/yellow]")
    if len(results) == 1 and results[0]["status"] == "added":
        result = results[0]
        pdf_file = Path(result["folder"]) / "paper.pdf"
        console.print(f"  entry.bib: {result['folder']}/entry.bib")
        console.print(
            f"  paper.pdf: {'stored' if pdf_file.is_file() else 'not stored'}"
        )
    elif len(results) > 1:
        added = sum(1 for result in results if result["status"] == "added")
        skipped = len(results) - added
        console.print(
            f"[dim]Added {added}, skipped {skipped}, {pdf_count} PDF(s) downloaded.[/dim]"
        )


def cmd_list(args: argparse.Namespace) -> None:
    papers = list_papers(category=args.cat)
    if not papers:
        if args.cat:
            console.print(f"No papers in category '{args.cat}'.")
        else:
            console.print("Library is empty. Add a paper with `cocotero add`.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Year")
    table.add_column("Authors")
    table.add_column("Title")
    table.add_column("Categories")
    table.add_column("PDF")
    for paper in papers:
        table.add_row(
            paper["key"],
            paper["year"],
            paper["authors"],
            paper["title"],
            paper["keywords"] or "—",
            "yes" if paper["has_pdf"] else "no",
        )
    console.print(table)


def cmd_cat(args: argparse.Namespace) -> None:
    try:
        if args.cat:
            added = toggle_keyword(args.key, args.cat)
            verb = "Added" if added else "Removed"
            console.print(
                f"[green]{verb}[/green] tag '{args.cat}' [bold]{args.key}[/bold]."
            )
        else:
            tags = keywords(args.key)
            listing = ", ".join(sorted(tags)) if tags else "(none)"
            console.print(f"Tags for [bold]{args.key}[/bold]: {listing}")
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def cmd_cats(_args: argparse.Namespace) -> None:
    counts = list_categories()
    if not counts:
        console.print(
            "No categories yet. Tag papers with `cocotero cat <key> <category>`."
        )
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", style="cyan")
    table.add_column("Papers")
    for category, count in counts:
        table.add_row(category, str(count))
    console.print(table)


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
    for result in results:
        set_keywords(result["key"], keywords(result["key"]) | {args.category})
    pdf_count = 0
    for result in results:
        if result["status"] == "added" and not result["pdf"]:
            paper = get_paper(result["key"])
            if paper is not None and download_pdf(paper).get("pdf"):
                pdf_count += 1
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


def _retry_missing_pdfs() -> None:
    missing = [paper for paper in list_papers() if not paper["has_pdf"]]
    if not missing:
        console.print("All papers have a PDF.")
        return
    console.print(f"Retrying {len(missing)} paper(s) without a PDF…")
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


def cmd_pdf(args: argparse.Namespace) -> None:
    try:
        if args.path:
            stored = link_pdf(args.key, args.path)
            console.print(f"[green]Linked[/green] [bold]{args.key}[/bold] → {stored}")
            return
        if args.key:
            paper = get_paper(args.key)
            if paper is None:
                console.print(f"[red]No paper with key '{args.key}'.[/red]")
                raise SystemExit(1)
            if paper["has_pdf"]:
                console.print(f"[yellow]{args.key}[/yellow] already has a PDF.")
                return
            outcome = download_pdf(paper, interactive=True)
            if outcome["pdf"]:
                console.print(
                    f"[green]{args.key}[/green] — PDF via {outcome['source']}"
                )
            else:
                console.print(f"[yellow]{args.key}[/yellow] — not found (paywalled).")
            return
        _retry_missing_pdfs()
    except StoreError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)


def cmd_rm(args: argparse.Namespace) -> None:
    paper = get_paper(args.key)
    if paper is None:
        console.print(f"[red]No paper with key '{args.key}'.[/red]")
        raise SystemExit(1)
    shutil.rmtree(Path(paper["folder"]))
    console.print(f"[green]Removed[/green] [bold]{args.key}[/bold].")


def _open_paper_url(key: str) -> None:
    paper = get_paper(key)
    if paper is None:
        console.print(f"[red]No paper with key '{key}'.[/red]")
        raise SystemExit(1)
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
        f'cat "{library}"/{{1}}/entry.bib; '
        f'echo; ls "{library}"/{{1}}/paper.pdf 2>/dev/null || echo "PDF: none"'
    )
    selected = fzf_select(lines, preview_cmd=preview)
    if selected is None:
        return None
    return selected.split("\t", maxsplit=1)[0]


def cmd_open(args: argparse.Namespace) -> None:
    key = args.key or _fzf_pick_paper(category=args.cat)
    if key is not None:
        _open_paper_url(key)


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
    add.set_defaults(func=cmd_add)

    list_parser = sub.add_parser("list", help="List all papers.")
    list_parser.add_argument("--cat", help="Only show papers with this category.")
    list_parser.set_defaults(func=cmd_list)
    open_parser = sub.add_parser(
        "open", help="Open a paper in your browser. Without a key, pick via fzf."
    )
    open_parser.add_argument("key", nargs="?")
    open_parser.add_argument(
        "--cat", help="Only fuzzy-pick among papers with this category."
    )
    open_parser.set_defaults(func=cmd_open)

    cat_parser = sub.add_parser("cat", help="Show or toggle a category tag on a paper.")
    cat_parser.add_argument("key")
    cat_parser.add_argument(
        "cat", nargs="?", help="Category to add/remove (omit to list tags)."
    )
    cat_parser.set_defaults(func=cmd_cat)

    sub.add_parser("cats", help="List categories with paper counts.").set_defaults(
        func=cmd_cats
    )

    cluster_parser = sub.add_parser(
        "cluster",
        help="Add a pasted bibliography and tag every paper with one category.",
    )
    cluster_parser.add_argument("category")
    cluster_parser.add_argument("text", nargs="*")
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
    pdf_parser.set_defaults(func=cmd_pdf)

    rm_parser = sub.add_parser("rm", help="Remove a paper from the library.")
    rm_parser.add_argument("key")
    rm_parser.set_defaults(func=cmd_rm)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
