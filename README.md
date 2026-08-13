# Cocotero

CLI paper manager (a minimal Zotero clone). BibTeX citations and PDFs are stored
as **plain documents** on disk — `grep` is your index, `fzf` is your search UI.

Built step by step; see [PLAN.md](PLAN.md) for the roadmap and current status.

## Setup

```sh
uv sync        # install deps into .venv
uv run cocotero --help
```

Install globally + tab completion (once):

```sh
uv tool install --from . cocotero   # puts `cocotero` on PATH
./scripts/install_completions.sh    # installs zsh/bash completion + enables compinit
```

## Usage

Everything auto-initializes on first run: the library is created at
`~/cocotero/library/` (config at `~/.config/cocotero/config.toml`). Override
with the env vars `COCOTERO_LIB` and `COCOTERO_CONFIG`.

```sh
# Add papers — auto-detects DOI / arXiv link / title / BibTeX.
# A pasted multi-entry BibTeX is added as a batch (duplicates are skipped).
cocotero add                          # then paste/type and press Enter
cocotero add "attention is all you need"
cocotero add 10.48550/arxiv.1706.03762
cocotero add https://arxiv.org/abs/1706.03762

# Inline BibTeX, with an optional PDF
cocotero add -b '@article{vaswani2017, ...}' --pdf paper.pdf

# Auto-cite: fuzzy-pick from Crossref by title, or fetch by DOI
cocotero add -t "attention is all you need"
cocotero add -d 10.48550/arxiv.1706.03762

# List everything (optionally filtered by category)
cocotero list
cocotero list --cat lit-review

# Open a paper in your browser: fuzzy-pick via fzf, or by key
cocotero open
cocotero open <key>
cocotero open --cat <category>        # pick only within a category

# Categories
cocotero cat <key> <category>         # toggle a tag on a paper
cocotero cat <key>                    # show a paper's tags
cocotero cats                         # category counts
cocotero cluster <category>           # paste a bibliography → add + tag all as one category

# PDFs (auto-downloaded on every add)
cocotero pdf                          # retry downloads for all papers missing a PDF
cocotero pdf <key>                    # retry one paper (may open your proxy page)
cocotero pdf <key> /path/to/file.pdf  # link a local PDF file

# Remove a paper
cocotero rm <key>
```

Each paper lives in its own folder:

```
~/cocotero/library/<key>/
  entry.bib    # BibTeX (+ injected url/doi/file/keywords fields)
  paper.pdf    # stored PDF (optional)
```

## Configuration

`~/.config/cocotero/config.toml`:

```toml
library = "~/cocotero/library"
unpaywall_email = ""                 # used for the Unpaywall API
proxy_prefix = ""                    # e.g. http://acces.bibl.ulaval.ca/login?url=
downloads_dir = "~/Downloads"        # watched during proxy handoff
pdf_priority = ["ieee", "semanticscholar", "unpaywall", "arxiv"]
```

## How PDFs are downloaded

1. **Semantic Scholar** — open-access PDF by title.
2. **Unpaywall** — open-access PDF by DOI (needs `unpaywall_email`).
3. **arXiv** — from the entry's arXiv URL, or by title search.
4. **EZproxy handoff** *(single adds only)* — if the DOI is from an institutional
   publisher (`10.1109`, `10.1016`, …) and `proxy_prefix` is set, your university
   proxy page opens in the browser and Cocotero watches `downloads_dir` for the
   downloaded PDF.

IEEE is resolved through Semantic Scholar / Unpaywall (IEEE direct download is
paywalled in practice), so the chain above is what matters.

## Roadmap

- [x] Step 1 — skeleton, storage, paste-add, `list`
- [x] Step 2 — `fzf` live-grep search + open in browser
- [x] Step 3 — auto-citation from title/DOI (Crossref)
- [x] Step 4 — duplicate tolerance + batch add
- [x] Step 5 — categories + batch clustering
- [x] Step 6 — PDF auto-download chain + EZproxy handoff
- [x] Step 7 — PDF repair (retry all/single, local link)
- [x] Step 8 — polish (`rm`, docs, completions, lint)
