# Cocotero

A CLI paper manager (a minimal Zotero clone) for scientific reading. Each paper
is stored as **plain documents** on disk — `grep` is your index, `fzf` is your
search UI. BibTeX metadata and PDFs stay readable, versionable, and portable.

- Add papers by **DOI**, **arXiv link**, **title**, or pasted **BibTeX**.
- Batch-add a whole bibliography; duplicates are auto-skipped.
- Auto-download **PDFs** from open-access sources, or hand off paywalled papers
  to your university EZproxy (assisted or fully automatic).
- Group papers into **clusters**, fuzzy-search with `fzf`, open in your browser,
  and cite with a single command.

## Requirements

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [fzf](https://github.com/junegunn/fzf) — used for interactive picking
  (`cocotero open`, `cocotero browse-cluster`, `cocotero cite`, `cocotero add -t`)

## Install

Install on any computer with a single command:

```sh
uv tool install --from git+https://github.com/nicolaslauzon/cocotero
```

This puts `cocotero` on your `PATH`. Optional — EZproxy support for automatic
PDF downloads of paywalled papers (installs Playwright + Chromium, ~150 MB):

```sh
uv tool install --from git+https://github.com/nicolaslauzon/cocotero --with playwright
~/.local/share/uv/tools/cocotero/bin/python -m playwright install chromium
```

Re-running the first line with `--with playwright` upgrades an existing install
in place. On Linux you may also need system browser libraries:
`playwright install-deps chromium` (requires sudo).

Tab completion for zsh/bash:

```sh
git clone https://github.com/nicolaslauzon/cocotero && ./cocotero/install.sh
```

Or run `install.sh` from a checkout — it installs the tool **and** completions.
Pass `--ezproxy` to also install Playwright + Chromium (see above).

### From a checkout

```sh
uv sync          # install deps into .venv
uv run cocotero --help
```

## Quick start

Everything auto-initializes on first run: the library is created at
`~/cocotero/library/` and config at `~/.config/cocotero/config.toml`. Override
with the env vars `COCOTERO_LIB` and `COCOTERO_CONFIG`.

```sh
cocotero add                          # paste a DOI, arXiv link, title, or BibTeX, press Enter
cocotero add "attention is all you need"
cocotero add 10.48550/arxiv.1706.03762
cocotero add https://arxiv.org/abs/1706.03762
cocotero open                         # fuzzy-pick a paper and open it in the browser
cocotero cite <key>                   # print the stored BibTeX entry
```

## Usage

### Adding papers

```sh
cocotero add                          # interactive: paste DOI / arXiv / title / BibTeX, Enter
cocotero add <doi | arxiv-url | title>   # same, inline (no quotes needed)
cocotero add -b '@article{vaswani2017, ...}' --pdf paper.pdf   # raw BibTeX + local PDF
cocotero add -t "attention is all you need"  # Crossref lookup + fzf pick
cocotero add -d 10.48550/arxiv.1706.03762   # fetch by DOI
```

Pasting a multi-entry BibTeX adds the whole bibliography as a batch; papers
already in the library are skipped with a message.

### Browsing and opening

```sh
cocotero open                        # fuzzy-pick via fzf, open in browser
cocotero open <key>                  # open a specific paper
cocotero browse-cluster <cluster>    # fuzzy-pick and open within one cluster
cocotero cite <key>                  # print the stored BibTeX entry
cocotero cite                        # fuzzy-pick a paper, print its BibTeX
```

### Clusters

Papers are organized into **clusters** (categories). A cluster is created when
you add a whole bibliography with `cluster`; `browse-cluster` lets you browse
one:

```sh
cocotero cluster <cluster>           # paste a bibliography → add all + tag all
cocotero cluster <cluster> --handoff auto   # auto-fetch paywalled PDFs too
cocotero browse-cluster <cluster>    # fuzzy-pick and open papers in that cluster
```

### PDFs

A PDF is auto-downloaded on every add. Retry or repair later:

```sh
cocotero pdf                         # retry downloads for all papers missing a PDF
cocotero pdf --handoff auto          # retry all, auto-fetch paywalled via EZproxy
cocotero pdf <key>                   # retry one paper (may open your proxy page)
cocotero pdf <key> /path/to/file.pdf # link a local PDF file
```

### Maintenance

```sh
cocotero clean                       # deduplicate + keep only user categories
cocotero clean --keep lit-review     # preserve specific categories when migrating
cocotero login                       # save an EZproxy session for auto PDF downloads
cocotero rm <key>                    # remove a paper
```

## Storage layout

The library is flat — one BibTeX file and one optional PDF file per paper:

```
~/cocotero/library/
  bib/<key>.bib    # BibTeX (+ injected url/doi/file/category fields)
  pdf/<key>.pdf    # stored PDF (optional)
```

Each file is named after the `{lastname}{year}` citation key (e.g.
`brossard2020`), with a `-2`, `-3`… suffix on collision. The key in any pasted
BibTeX is always rewritten to match. The injected `file` field points to the
stored PDF as `:pdf/<key>.pdf:PDF`.

## Configuration

`~/.config/cocotero/config.toml`:

```toml
library = "~/cocotero/library"
unpaywall_email = ""                 # used for the Unpaywall API
proxy_prefix = ""                    # e.g. http://acces.bibl.ulaval.ca/login?url=
downloads_dir = "~/Downloads"        # watched during proxy handoff
pdf_priority = ["ieee", "semanticscholar", "unpaywall", "crossref", "arxiv"]
handoff_mode = "assisted"            # or "auto" (headless EZproxy via Playwright)
libkey_library_id = ""               # Third Iron ID, e.g. 2414 for Université Laval
```

## How PDFs are downloaded

All sources are queried **in parallel**; the first URL that yields a real PDF
wins (in `pdf_priority` order).

Papers without a DOI are resolved via Crossref **by title** first — the matching
DOI is saved into `bib/<key>.bib`, so Unpaywall, Crossref links, and the EZproxy
handoff all apply on that and future runs.

1. **Semantic Scholar** — open-access PDF by DOI (title fallback).
2. **Unpaywall** — open-access PDF by DOI (needs `unpaywall_email`); landing
   pages like arXiv abs / MDPI are converted to direct PDF URLs.
3. **Crossref** — `application/pdf` links from the work's metadata.
4. **arXiv** — from the entry's arXiv URL, or by title search.

IEEE is resolved through Semantic Scholar / Unpaywall / Crossref (IEEE direct
download is paywalled in practice).

### Institutional access (paywalled papers)

If the DOI is from an institutional publisher (`10.1109`, `10.1016`, …) and
`proxy_prefix` is set:

- **assisted** *(default)* — your university proxy page opens in the browser and
  Cocotero watches `downloads_dir` for the downloaded PDF.
- **auto** — run `cocotero login` once (opens a Chromium window to sign in to
  EZproxy, session saved), then pass `--handoff auto` (or set
  `handoff_mode = "auto"`) to fetch paywalled PDFs silently headless.

If `libkey_library_id` is set (your library's Third Iron ID — e.g. `2414` for
Université Laval), the headless flow first resolves each DOI through
`libkey.io/libraries/<id>/<doi>` and follows LibKey's direct full-text link,
which already knows the best route through your subscriptions or open access —
falling back to the publisher page only when that fails. The one-time
`cocotero login` step also opens your libkey.io page so you can pick your
organization and check "Download PDF".

## Development

```sh
uv sync                   # install deps
uv run pytest             # run the test suite
uv run ruff check .       # lint
uv run ruff format .      # format
```