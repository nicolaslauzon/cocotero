import argparse
import re
import sys
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
from .store import (
    StoreError,
    get_paper,
    list_papers,
    resolve_paper_url,
    search_index,
    store_papers,
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
    if (doi := _extract_doi(text)):
        console.print(f"[dim]Detected DOI: {doi}[/dim]")
        return _lookup_by_doi(doi)
    if (arxiv_id := _extract_arxiv(text)):
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
        f"{hit['doi']}\t{hit['year']} {hit['authors']} — {hit['title']}"
        for hit in hits
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
    for result in results:
        if result["status"] == "added":
            console.print(f"[green]Added[/green] [bold]{result['key']}[/bold] — {result['title']}")
        else:
            console.print(f"[yellow]Skipped[/yellow] [bold]{result['key']}[/bold] — already in library")
    if len(results) == 1 and results[0]["status"] == "added":
        result = results[0]
        console.print(f"  entry.bib: {result['folder']}/entry.bib")
        console.print(f"  paper.pdf: {result['pdf'] or 'not stored'}")
    elif len(results) > 1:
        added = sum(1 for result in results if result["status"] == "added")
        skipped = len(results) - added
        console.print(f"[dim]Added {added}, skipped {skipped}.[/dim]")


def cmd_list(_args: argparse.Namespace) -> None:
    papers = list_papers()
    if not papers:
        console.print("Library is empty. Add a paper with `cocotero add`.")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Year")
    table.add_column("Authors")
    table.add_column("Title")
    table.add_column("PDF")
    for paper in papers:
        table.add_row(
            paper["key"],
            paper["year"],
            paper["authors"],
            paper["title"],
            "yes" if paper["has_pdf"] else "no",
        )
    console.print(table)


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


def _fzf_pick_paper() -> str | None:
    lines = search_index()
    if not lines:
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
    key = args.key or _fzf_pick_paper()
    if key is not None:
        _open_paper_url(key)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocotero", description="CLI paper manager.")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add a paper: paste a DOI, arXiv link, title, or BibTeX.")
    add.add_argument("text", nargs="*", help="DOI, arXiv link, title, or BibTeX (auto-detected; no quotes needed).")
    add.add_argument("-b", "--bib", help="Raw BibTeX text (instead of interactive paste).")
    add.add_argument("--pdf", help="Path to a PDF to store alongside the entry.")
    add.add_argument("-t", "--title", help="Article title (Crossref lookup + fzf pick).")
    add.add_argument("-d", "--doi", help="DOI (Crossref BibTeX lookup).")
    add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List all papers.").set_defaults(func=cmd_list)
    open_parser = sub.add_parser("open", help="Open a paper in your browser. Without a key, pick via fzf.")
    open_parser.add_argument("key", nargs="?")
    open_parser.set_defaults(func=cmd_open)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()