# AGENTS.md

## Project Overview

Cocotero is a CLI paper manager (minimal Zotero clone) for scientific reading.
It stores each paper as **plain documents** in `~/cocotero/library/<key>/`:
`entry.bib` (BibTeX with injected `url`/`doi`/`file` fields) and an optional
`paper.pdf`. Grep over the library is the index; `fzf` is the search UI.

Full roadmap and per-step specs: **[PLAN.md](PLAN.md)**. Read it before working
— it tracks which step is next and what each step must build. Implement one step
at a time and stop for validation.

## Tech Stack

- Python >=3.11, managed with **uv** (see `.python-version`)
- `src/` layout, package name `cocotero`
- Deps: `requests`, `bibtexparser` (v2 beta API), `rich`
- Interactive picking uses the external `fzf` binary (installed at `/usr/bin/fzf`)
- CLI: stdlib `argparse` (no click/typer)

## Setup Commands

```sh
uv sync                    # install deps into .venv
uv run cocotero --help     # run the CLI
uv run cocotero add        # paste DOI, arXiv link, title, or BibTeX, press Enter

# optional global install + tab completion
uv tool install --from . cocotero
./scripts/install_completions.sh
```

Environment overrides (used heavily by tests): `COCOTERO_LIB` and
`COCOTERO_CONFIG` point the library dir and config file elsewhere. The config +
library auto-create on first run — there is deliberately **no** `init` command.

## Testing Instructions

- Run all tests: `uv run pytest`
- Config lives in `pyproject.toml` under `[tool.pytest.ini_options]`.
  NOTE: this machine has ROS (jazzy) on `PYTHONPATH` whose pytest plugins crash
  (missing `yaml`); they are disabled via `addopts` — keep that line intact.
- Tests live in `tests/test_store.py` (pytest). They monkeypatch `COCOTERO_LIB` /
  `COCOTERO_CONFIG` to a tmp dir, so no test touches the real library.
- Add a test for any new `store.py` behavior (slugify, keys, dedup, storage).

## Code Style

Strict standards — code must be 100% self-documenting:

- **Zero comments & zero docstrings** in code: no inline comments, block
  comments, docstrings, or explanatory notes. Structure, function names, and
  variable names carry all meaning.
- **PEP 8** formatting/naming; **PEP 484** explicit type hints on all
  parameters, returns, and ambiguous variables.
- **Modern Python (3.11+):** built-in generics (`list[str]`, `int | None`),
  `pathlib`, `dataclass`, `enum`, `TypedDict`; no `typing.List`/`Optional`, no
  utility helpers that stdlib provides.
- **KISS / DRY / SOLID:** small single-responsibility functions, no deep
  nesting or monster methods; Pythonic idioms (comprehensions, generators,
  context managers).
- Keep modules small and single-purpose (see PLAN.md "Modules"):
  - `config.py` — lazy config/library init
  - `store.py` — on-disk storage, bibkeys, dedup, listing
  - `citations.py` — Crossref lookups (Step 3)
  - `download.py` — PDF source chain + EZproxy handoff (Step 4)
  - `ui.py` — `fzf_select` + `open_in_browser`
  - `cli.py` — argparse subcommands; the only place args are parsed
- Private helpers prefixed `_`; no `from __future__ import annotations`.
- User-facing problems raise `StoreError` (or a similar domain exception) and
  are printed via `rich.console` in `cli.py` with a non-zero exit.

## Key Conventions / Gotchas

- `bibtexparser` is v2 beta: use `parse_string`, `write_string(Library([entry]))`
  (it does NOT accept a bare `Entry`), `entry.get(field)` returns a `Field` or
  `None` (use `.value`), and `entry.key` is the citation key.
- Malformed BibTeX is parsed **leniently** — 0 entries, not an exception. Always
  guard on empty `library.entries`.
- Folder name == generated `{lastname}{year}` citation key (all lowercase, e.g.
  `brossard2020`); the key in the pasted BibTeX is always rewritten to match.
- Pasted BibTeX is sanitized of ANSI escape sequences (`\x1bE`, CSI, ...) before
  parsing — bibtexparser's lenient parser otherwise bakes them into field keys.
- Same DOI already in library → hard error, no duplicate.
- PDF priority order is IEEE → Semantic Scholar → Unpaywall → arXiv (stored in
  config `pdf_priority`). Institutional access = EZproxy `proxy_prefix` + watch
  `downloads_dir` (~/Downloads) for browser-downloaded PDFs.
- When in doubt about where a feature belongs or which step it is, check PLAN.md
  and follow the current step's spec exactly.

## Commit / PR Notes

- One commit per validated step. Message style: `step N: <summary>`.
- Before committing: `uv run pytest` must be green.
- This repo is freshly `uv init`ed; no CI pipeline is configured yet.