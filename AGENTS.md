# AGENTS.md

## Project Overview

Cocotero is a CLI paper manager (minimal Zotero clone). Each paper is stored as
plain documents in `~/cocotero/library/`: `bib/<key>.bib` (BibTeX with injected
`url`/`doi`/`file`/`category` fields) and an optional `pdf/<key>.pdf`. Grep over
the library is the index; `fzf` is the search UI. The CLI is fully built — no
roadmap is tracked; README.md documents all commands.

## Stack & Setup

- Python >=3.11, managed with **uv** (`src/` layout, package `cocotero`, stdlib
  `argparse`). Deps: `requests`, `bibtexparser` (v2 beta), `rich`; optional
  extra `ezproxy` (`playwright`).
- Commands: `uv sync`; `uv run cocotero --help`; `uv run pytest`;
  `uv run ruff check .`; `uv run ruff format .`.
- Tests in `tests/` monkeypatch `COCOTERO_LIB`/`COCOTERO_CONFIG` to a tmp dir, so
  no test touches the real library. Library + config auto-create on first run —
  there is deliberately **no** `init` command.
- `pyproject.toml` `addopts` disables ROS pytest plugins on this machine — keep
  that line intact.

## Code Style

- **Zero comments & zero docstrings**; PEP 8; PEP 484 explicit type hints.
- Modern Python 3.11+ (built-in generics, `pathlib`, `dataclass`, `TypedDict`),
  no `typing.List`/`Optional`, no `from __future__ import annotations`.
- Small single-responsibility functions; private helpers prefixed `_`.
- Modules: `config.py` (lazy config/library init), `store.py` (storage, bibkeys,
  dedup, categories), `citations.py` (Crossref/arXiv lookups),
  `download.py` (parallel PDF discovery + EZproxy handoff), `ezproxy.py`
  (Playwright login/auto-fetch), `ui.py` (`fzf_select`, `open_in_browser`),
  `cli.py` (argparse; only place args are parsed).
- User-facing problems raise `StoreError` (or similar) and are printed via
  `rich.console` in `cli.py` with a non-zero exit.

## Gotchas

- `bibtexparser` v2 beta: use `parse_string`, `write_string(Library([entry]))`
  (NOT a bare `Entry`), `entry.get(field)` returns a `Field` or `None` (use
  `.value`). Malformed BibTeX parses leniently — 0 entries, not an exception;
  always guard on empty `library.entries`. Sanitize ANSI escapes before parsing.
- Bib/pdf file name == generated `{lastname}{year}` key, all lowercase (e.g.
  `bib/brossard2020.bib`, `-2` suffix on collision); the pasted BibTeX key is
  always rewritten to match. The injected `file` field is `:pdf/<key>.pdf:PDF`.
- Dedup: same DOI (or same normalized title when no DOI) already in library →
  **skip** with a message, never a hard error; batches keep going. One-shot
  `LibraryIndex` per batch.
- User categories live in the `category` field; bibliographic `keywords` are
  stripped on store. `clean_library` migrates legacy `keywords` → `category`
  (keeping only `--keep` cats).
- PDF sources queried in parallel; first real PDF wins in `pdf_priority` order.

## Commit Notes

- One commit per logical change, style: `step N: <summary>`. `uv run pytest` and
  `uv run ruff check .` must be green before committing.