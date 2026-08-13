# Cocotero — Build Plan

CLI paper manager (Zotero clone) for scientific reading. All state lives as **plain documents** on disk; `grep` is the index, `fzf` is the search UI. Built step by step; each step is independently validatable before the next begins.

## Decisions (locked)

- **Stack:** Python 3.12 + `uv`. Deps: `requests`, `bibtexparser`, `rich`. Everything else stdlib (`tomllib`, `argparse`, `webbrowser`, `subprocess`).
- **Search UI:** external `fzf` (already installed at `/usr/bin/fzf`).
- **Storage:** folder-per-paper in `~/cocotero/library/`.
- **BibTeX input:** raw text pasted into the command (Ctrl+C/Ctrl+V), not files. A file path is a secondary fallback only.
- **`init` is automatic:** library dir + config auto-create on first run of any command (lazy init). There is **no** `init` command.
- **Institutional access:** EZproxy-style `proxy_prefix` + Firefox `~/Downloads` watch for browser-assisted PDF handoff.
- **PDF priority:** IEEE → Semantic Scholar → Unpaywall → arXiv.

## Storage model

```
~/cocotero/library/
  <bibkey>/
    entry.bib     # BibTeX + injected fields: file, url, doi, keywords
    paper.pdf     # optional; absent when paywalled
```

- `bibkey` = `{lastname}{year}`, all lowercase (e.g. `brossard2020`). The key
  provided in the pasted BibTeX is **always** rewritten to this scheme; `-2`,
  `-3` suffix on collision.
- Injected BibTeX fields:
  - `file = {:paper.pdf:PDF}` — links the stored PDF
  - `url` — landing page (opens in browser)
  - `doi` — used for dedup + download
  - `keywords = {cat1, cat2}` — categories
- **Dedup rule:** a paper already present (same DOI, or same normalized title when
  no DOI) is **skipped** with a message — never a hard error. Batch adds continue.

## Config

`~/.config/cocotero/config.toml`, auto-created on first run:

```toml
library = "~/cocotero/library"
unpaywall_email = ""               # set later, only needed for Unpaywall
proxy_prefix = ""                  # e.g. https://ezproxy.youruni.edu/login?url=
downloads_dir = "~/Downloads"      # Firefox default; watched for new PDFs
pdf_priority = ["ieee", "semanticscholar", "unpaywall", "arxiv"]
```

## Modules (`src/cocotero/`)

- `cli.py` — `argparse` subcommands; the only place that parses args.
- `config.py` — load/create config + library dir (lazy init); shared `user_agent`.
- `store.py` — bibkey gen, slugify, write/read `entry.bib`, copy/link PDF, dedup, keywords, list library.
- `citations.py` — Crossref search/fetch by title or DOI → BibTeX text.
- `download.py` — PDF source chain + EZproxy handoff + Downloads watch.
- `ui.py` — `fzf_select(items, preview_cmd)` wrapper + `open_in_browser(url)`.

## Commands

| Command | Purpose |
|---|---|
| `cocotero add` | single or batch add; auto-detects DOI / arXiv / title / BibTeX |
| `cocotero add -b "<raw bibtex>"` | inline paste; `--pdf path.pdf` optional |
| `cocotero add -t "<title>"` / `-d <doi>` | auto bibtex |
| `cocotero open [key] [--cat X]` | no key: fzf pick → open in browser; filter by category |
| `cocotero list [--cat X]` | table of papers (optionally one category) |
| `cocotero cat <key> [<cat>]` | toggle a category tag; show tags without a category |
| `cocotero cats` | category counts |
| `cocotero cluster <category>` | paste a bibliography → add all + tag all with the category |
| `cocotero pdf [key] [path]` | retry PDFs (all or one); link a local PDF file |
| `cocotero rm <key>` | delete a paper folder |

## Add flow (interactive — the "easiest" path)

1. **Smart input:** `cocotero add` takes text as positional args (no quoting
   needed for multi-word titles) or reads what you type/paste on **Enter**.
   Auto-detect: starts with `@` → BibTeX (keep reading lines until the entry
   closes with `}`; multiple entries → batch); matches a DOI (incl.
   `doi.org/...` URL) → Crossref fetch; matches `arxiv.org/(abs|pdf)/...` →
   arXiv API fetch; else → Crossref title search + fzf pick.
2. Store → duplicates are skipped with a message. A PDF is auto-downloaded after
   storing (or, for a single add, the EZproxy handoff opens if paywalled).
3. Print summary: key, title, stored path, PDF source ✓/✗.

## PDF download chain (`download.py`)

For each source in `pdf_priority`, try in order; first hit wins. IEEE is not a
dedicated source — IEEE OA is resolved via Semantic Scholar / Unpaywall (IEEE
direct is paywalled in practice):

1. **Semantic Scholar** — `GET api.semanticscholar.org/graph/v1/paper/search?query={title}&fields=openAccessPdf,externalIds` → `openAccessPdf.url`.
2. **Unpaywall** — `GET api.unpaywall.org/v2/{doi}?email=` (needs email; skipped if unset).
3. **arXiv** — from the entry's `arxiv.org/...` URL, or via `export.arxiv.org/api/query` by title → `arxiv.org/pdf/<id>`.

### Institutional fallback (browser handoff, single adds only)

All direct sources fail + DOI is an institutional publisher (`10.1109`,
`10.1016`, `10.1007`, …) + `proxy_prefix` set + adding a **single** paper:

1. Print `Paywalled — opening your university proxy page in your browser…`.
2. Open `proxy_prefix + <article url>` in the default browser.
3. Snapshot `downloads_dir` baseline, then watch for a **new** `.pdf` (~5 min
   timeout). New file → copy to `<key>/paper.pdf`, inject `file` field. Multiple
   candidates → pick via fzf.
4. Timeout → entry saved without PDF; recover with `cocotero pdf <key>`.
5. If `proxy_prefix` unset → skip handoff, just print the paywalled note.
6. Batch adds / `cluster` / `pdf` retry never hand off — they report "not found".

---

## Step 1 — Skeleton + storage + paste-add + list

**Goal:** running any command auto-creates the library + config; pasting BibTeX (+ optional PDF) lands plain `entry.bib` / `paper.pdf` on disk; `list` renders them.

**Build:**
1. `uv init`; `pyproject.toml` with `[project.scripts] cocotero = "cocotero.cli:main"`, deps `requests`, `bibtexparser`.
2. `config.py` — lazy init: create `~/cocotero/library/` + default `config.toml` if missing.
3. `store.py` — `slugify`, `make_bibkey`, `store_paper(bib_text, pdf_path=None)`, `list_papers()`, DOI dedup.
4. `cli.py` — `add` (wizard mode 1 + `-b/--bib` raw text + `--pdf`; modes 2/3 stubbed), `list`.
5. `ui.py` — `open_in_browser` stub (used later).
6. Tests for `slugify` / `make_bibkey` / dedup; `README.md` stub.

**Acceptance:**
- `cocotero add` (or any command) auto-creates `~/cocotero/library/` + config — no manual init.
- Paste BibTeX, optionally `--pdf`, files land as plain docs.
- `cocotero list` renders the entry.
- `uv run pytest` passes.

**Status: done**

## Step 2 — fzf search + browser open

**Goal:** `cocotero open` fuzzy-picks the library with arrows; Enter opens the article URL in the default browser.

**Build:**
- `ui.fzf_select(items, preview_cmd)`; `store.search_index()` builds lines `[key] {year} {authors} — {title}`.
- `open [key]` — no key: fzf with preview showing `entry.bib` + PDF status; on enter, resolve `url` (or DOI) and open in browser. With key: open directly.
- DOI→URL resolution for entries lacking `url`; `open_in_browser` via `xdg-open` (stderr silenced).
- Tab completion: `completions/_cocotero` (zsh) + `completions/cocotero.bash` (keys globbed from the library dir); `scripts/install_completions.sh` installs + enables compinit.

**Acceptance:** `cocotero open`, type, arrow around, Enter opens browser; `open <key>` works; `open bross<Tab>` completes.

**Status: done**

## Step 3 — Auto-citation by title/DOI

**Goal:** `add -t "<title>"` or `-d <doi>` fetches BibTeX automatically.

**Build:**
- `citations.py` — Crossref `works?query.bibliographic={title}&rows=8` → hits (doi, title, authors, year, container); pipe results through fzf to pick the right match; fetch BibTeX via DOI content negotiation `https://doi.org/{doi}` with `Accept: application/x-bibtex` (works for DataCite DOIs like arXiv's `10.48550`, where Crossref's `/transform` 404s); add `url` + `doi` fields; store.
- Wire wizard modes 2/3 (`add -t` / `add -d`).

**Acceptance:** `cocotero add -t "attention is all you need"` → pick match → entry saved with bibtex; `add -d <doi>` saves directly; duplicate DOI → skipped.

**Status: done**

## Step 4 — Duplicate tolerance + batch add

**Goal:** adding an already-known paper skips it with a message (no hard error);
a pasted multi-entry BibTeX is added as a batch.

**Build:**
- `store_paper` returns `status: added|skipped` + `existing_key`; dedup by DOI or
  normalized title (title only when no DOI). `store_papers` parses every entry
  and stores each, continuing past duplicates.
- `add` auto-detects multi-entry BibTeX → batch; positional `text` is
  `nargs="*"` (unquoted multi-word titles join into one query).

**Acceptance:** add the same paper twice → `Already in library — skipped`; paste a
10-entry bibliography → 10 papers, duplicates skipped.

**Status: done**

## Step 5 — Categories + batch clustering

**Goal:** tag papers and cluster a pasted bibliography under one category.

**Build:**
- `keywords` field in `entry.bib`; store helpers `keywords`, `set_keywords`,
  `toggle_keyword`, `list_categories`; `list_papers(category)` /
  `search_index(category)` filters.
- Commands: `cat <key> [<cat>]`, `cats`, `list --cat`, `open --cat`,
  `cluster <category>` (add-all + tag-all, existing papers included).

**Acceptance:** tag 2 papers, `cats` counts, `cluster lit-review` tags the whole
pasted bibliography (existing entries included).

**Status: done**

## Step 6 — PDF auto-download on add

**Goal:** every add (single, batch, cluster) tries to download the PDF and reports
the source used; single-add paywalled papers trigger the EZproxy handoff.

**Build:** `download.py` chain (SS → Unpaywall → arXiv) + `_fetch_pdf` (`%PDF`
check) + EZproxy handoff (interactive single adds only); `link_pdf` injects the
`file` field. User config set: `unpaywall_email = "nilau28@ulaval.ca"`,
`proxy_prefix = "http://acces.bibl.ulaval.ca/login?url="`.

**Acceptance:** add an arXiv paper → `paper.pdf` stored with source reported; a
paywalled IEEE paper → proxy page opens and `~/Downloads` is watched.

**Status: done**

## Step 7 — PDF repair

**Goal:** backfill missing PDFs and link local files.

**Build:** `pdf` command — `pdf` retries all missing (4-worker pool), `pdf <key>`
retries one (handoff allowed), `pdf <key> <path>` links a local file.

**Acceptance:** papers without PDFs get retried; a manual PDF is linked by path.

**Status: done**

## Step 8 — Polish

**Build:** `rm <key>`; ruff (dev dep) check + format across src/tests; full
`README.md`; completions for all commands; `AGENTS.md`/`PLAN.md` updated.

**Acceptance:** full workflow end-to-end; `uv run pytest` and
`uv run ruff check` green.

**Status: done**