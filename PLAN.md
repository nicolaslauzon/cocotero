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
- **Dedup rule:** same DOI already present → abort with a message pointing at the existing key.

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
- `config.py` — load/create config + library dir (lazy init).
- `store.py` — bibkey gen, slugify, write/read `entry.bib`, copy PDF, DOI dedup, list library.
- `citations.py` — Crossref search/fetch by title or DOI → BibTeX text. *(Step 3)*
- `download.py` — PDF source chain + institutional browser handoff. *(Step 4)*
- `ui.py` — `fzf_select(items, preview_cmd)` wrapper + `open_in_browser(url)`.

## Commands

| Command | Purpose |
|---|---|
| `cocotero add` | interactive wizard (see Add flow) |
| `cocotero add -b "<raw bibtex>"` | inline paste; `--pdf path.pdf` optional |
| `cocotero add -t "<title>"` / `-d <doi>` | auto bibtex + PDF (Steps 3–4) |
| `cocotero open [key]` | no key: fzf pick → open in browser; with key: open that paper |
| `cocotero list` | table of all papers |
| `cocotero cat <key> <cat>` | tag/untag; `cat <key>` shows tags |
| `cocotero cats` | category counts |
| `cocotero rm <key>` | delete a paper folder |

## Add flow (interactive wizard — the "easiest" path)

1. Prompt: *how do you want to add?* → `[1] Paste BibTeX  [2] Article title  [3] DOI  [4] BibTeX + PDF files`.
2. **Smart input:** `cocotero add` also takes the text as a positional arg (`cocotero add "<title>"`), or interactively reads what you type/paste and submits on **Enter**. Auto-detect: starts with `@` → BibTeX (keep reading lines until the entry closes with `}`); matches a DOI (incl. `doi.org/...` URL) → Crossref fetch; matches `arxiv.org/(abs|pdf)/...` → arXiv API fetch; else → Crossref title search + fzf pick.
3. Steps 3–4 make modes 2/3 fully automatic; until then they print a friendly "coming soon" and fall back to paste.
4. Save → print summary: key, title, stored path, pdf ✓/✗.

## PDF download chain (`download.py`) — IEEE first

For each source in `pdf_priority`, try in order; first hit wins:

1. **IEEE** — if DOI prefix `10.1109`: resolve DOI → IEEE page; keep only if marked open access; else skip. *(Realistic outcome: paywalled → fall through.)*
2. **Semantic Scholar** — `GET api.semanticscholar.org/graph/v1/paper/search?query={title}&fields=openAccessPdf,externalIds` → `openAccessPdf.url`. Also yields arXiv ID for step 4.
3. **Unpaywall** — `GET api.unpaywall.org/v2/{doi}?email=` (needs email; if unset, skip with note).
4. **arXiv** — if arXiv ID known (from SS) or via `export.arxiv.org/api/query` by title → `arxiv.org/pdf/<id>`.

### Institutional fallback (browser handoff)

All direct sources fail + DOI is an institutional publisher (`10.1109`, `10.1016`, `10.1007`, …) + `proxy_prefix` set:

1. Print `Paywalled — opening your university proxy page in your browser. Download the PDF and I'll import it.`
2. Open `proxy_prefix + <article url>` in the default browser (Firefox SSO session is already there).
3. Snapshot `downloads_dir` baseline, then watch for a **new** `.pdf` (~5 min timeout). New file → copy to `<key>/paper.pdf`, inject `file` field. Multiple candidates → pick via fzf.
4. Timeout → entry saved without PDF; recover later with `add --pdf`.
5. If `proxy_prefix` unset → skip handoff, just print the paywalled note.

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

**Acceptance:** `cocotero add -t "attention is all you need"` → pick match → entry saved with bibtex; `add -d <doi>` saves directly; duplicate DOI → dedup error.

**Status: done**

## Step 4 — PDF download chain + institutional handoff

**Goal:** auto-download PDF with IEEE→SS→Unpaywall→arXiv priority; graceful "paywalled" when none; EZproxy browser handoff + Downloads watch.

**Build:** `download.py` as specced above; `add` saves PDF into `paper.pdf`, injects `file` field, reports source used. Config `unpaywall_email` prompt the first time Unpaywall is reached; `proxy_prefix` / `downloads_dir` used for handoff.

**Acceptance:** add a known arXiv-hosted paper → PDF downloaded; a paywalled IEEE paper → clean message + browser handoff, entry saved.

## Step 5 — Categories

**Goal:** cluster papers (e.g. "paper-im-writing").

**Build:** `cat <key> <cat>` toggles tag in `keywords`; `cats` lists counts; `open --cat X` and `list --cat X` filter.

**Acceptance:** tag 2 papers, `cats`, `search --cat`.

## Step 6 — Polish

**Build:** `rm <key>`; harden dedup + error messages; edge cases (unparseable bib, no year, network fail); full `README.md`; `uv run pytest`.

**Acceptance:** full workflow end-to-end.