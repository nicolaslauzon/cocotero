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
# Add a paper — auto-detects DOI / arXiv link / title / BibTeX
cocotero add                          # then paste/type and press Enter
cocotero add "attention is all you need"
cocotero add 10.48550/arxiv.1706.03762
cocotero add https://arxiv.org/abs/1706.03762

# Inline BibTeX, with an optional PDF
cocotero add -b '@article{vaswani2017, ...}' --pdf paper.pdf

# Auto-cite: fuzzy-pick from Crossref by title, or fetch by DOI
cocotero add -t "attention is all you need"
cocotero add -d 10.48550/arxiv.1706.03762

# List everything
cocotero list

# Open a paper in your browser: fuzzy-pick via fzf (type to filter, arrows, Enter)
cocotero open

# Open by key — Tab autocompletes keys, Tab-Tab lists them
cocotero open <key>
```

Each paper lives in its own folder:

```
~/cocotero/library/<key>/
  entry.bib    # BibTeX (+ injected url/doi/file fields)
  paper.pdf    # stored PDF (optional)
```

## Roadmap

- [x] Step 1 — skeleton, storage, paste-add, `list`
- [x] Step 2 — `fzf` live-grep search + open in browser
- [x] Step 3 — auto-citation from title/DOI (Crossref)
- [ ] Step 4 — PDF download chain (IEEE → Semantic Scholar → Unpaywall → arXiv) + EZproxy handoff
- [ ] Step 5 — categories/tags
- [ ] Step 6 — polish (`rm`, dedup, docs)