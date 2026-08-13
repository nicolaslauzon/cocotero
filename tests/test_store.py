import pytest

from cocotero import store
from cocotero.store import StoreError


@pytest.fixture()
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


BIB = """@article{vaswani2017attention,
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  title = {Attention is All You Need},
  year = {2017},
  doi = {10.48550/arxiv.1706.03762}
}"""

BATCH = BIB + """
@article{brossard2020,
  author = {Brossard, Martin and Bonnabel, Silvere},
  title = {Denoising IMU},
  year = {2020},
  doi = {10.1109/LRA.2020.3003256}
}"""


def test_slugify():
    assert store.slugify("Attention is All You Need!") == "attention-is-all-you-need"
    assert store.slugify("Café à Paris") == "cafe-a-paris"
    assert store.slugify("!!!") == "untitled"


def test_make_bibkey():
    assert store.make_bibkey("Vaswani", "2017") == "vaswani2017"
    assert store.make_bibkey("Brossard", "2020") == "brossard2020"
    assert store.make_bibkey("van der Berg", "1999") == "van-der-berg1999"


def test_first_author_lastname():
    assert store.first_author_lastname("Vaswani, Ashish and Shazeer, Noam") == "Vaswani"
    assert store.first_author_lastname("Ashish Vaswani") == "Vaswani"
    assert store.first_author_lastname("") == ""


def test_store_paper_plain_docs(library):
    result = store.store_paper(BIB)
    folder = library / result["key"]
    assert result["key"] == "vaswani2017"
    assert folder.is_dir()
    assert (folder / "entry.bib").is_file()
    assert not result["pdf"]
    assert (folder / "entry.bib").read_text().startswith("@article{vaswani2017,")


def test_store_paper_injects_url(library):
    result = store.store_paper(BIB)
    text = (library / result["key"] / "entry.bib").read_text()
    assert "url = {https://doi.org/10.48550/arxiv.1706.03762}" in text


def test_store_paper_with_pdf(library):
    pdf = library / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    result = store.store_paper(BIB, pdf_path=str(pdf))
    assert result["pdf"] == str(library / result["key"] / "paper.pdf")
    text = (library / result["key"] / "entry.bib").read_text()
    assert "file = {:paper.pdf:PDF}" in text


def test_store_paper_duplicate_doi(library):
    first = store.store_paper(BIB)
    second = store.store_paper(BIB.replace("vaswani2017attention", "copy2017"))
    assert second["status"] == "skipped"
    assert second["existing_key"] == "vaswani2017"
    assert len(list(library.glob("*/entry.bib"))) == 1


def test_store_paper_duplicate_title_without_doi(library):
    first = store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={Attention is all you need!}}"
    )
    second = store.store_paper(
        "@article{y, author={Vaswani, Ashish}, year={2017}, title={Attention Is All You Need}}"
    )
    assert first["status"] == "added"
    assert second["status"] == "skipped"
    assert second["existing_key"] == first["key"]


def test_store_paper_same_title_different_doi_not_duplicate(library):
    first = store.store_paper(BIB)
    second = store.store_paper(BIB.replace("10.48550/arxiv.1706.03762", "10.9999/different"))
    assert first["status"] == "added"
    assert second["status"] == "added"


def test_store_papers_batch(library):
    results = store.store_papers(BATCH)
    assert [r["status"] for r in results] == ["added", "added"]
    assert len(list(library.glob("*/entry.bib"))) == 2


def test_store_papers_batch_skips_duplicates(library):
    dup = (
        "@article{vaswani2017copy, author={Vaswani, Ashish}, year={2017}, "
        "title={Attention is All You Need}, doi={10.48550/arxiv.1706.03762}}"
    )
    results = store.store_papers(BATCH + "\n" + dup)
    assert [r["status"] for r in results] == ["added", "added", "skipped"]
    assert len(list(library.glob("*/entry.bib"))) == 2


def test_store_papers_bad_bibtex(library):
    with pytest.raises(StoreError, match="No BibTeX entries found"):
        store.store_papers("not bibtex at all")


def test_store_paper_collision_suffix(library):
    first = store.store_paper(BIB)
    second = store.store_paper(BIB.replace("10.48550/arxiv.1706.03762", "10.9999/different"))
    assert second["key"] == f"{first['key']}-2"


def test_store_paper_bad_bibtex(library):
    with pytest.raises(StoreError, match="No BibTeX entries found"):
        store.store_paper("@article{broken title={x}")


def test_store_paper_rewrites_key(library):
    result = store.store_paper(BIB.replace("vaswani2017attention", "Brossard2020"))
    assert result["key"] == "vaswani2017"
    assert (library / "vaswani2017").is_dir()
    assert not (library / "Brossard2020").exists()
    assert (library / "vaswani2017" / "entry.bib").read_text().startswith("@article{vaswani2017,")


def test_store_paper_sanitizes_escape_codes(library):
    dirty = "@article{Brossard2020,\n\t\x1bE   author = {Martin Brossard and Silvere Bonnabel},\n\t\x1bE   doi = {10.1109/LRA.2020.3003256},\n\t\x1bE   year = {2020}\n}"
    result = store.store_paper(dirty)
    text = (library / result["key"] / "entry.bib").read_text()
    assert result["key"] == "brossard2020"
    assert "\x1b" not in text
    assert "author = {Martin Brossard and Silvere Bonnabel}" in text
    assert "doi = {10.1109/LRA.2020.3003256}" in text


def test_normalize_library_renames_old_keys(library):
    brossard = "@article{Brossard2020, author={Brossard, Martin}, year={2020}, title={Denoising IMU}}"
    old = library / "Brossard2020"
    old.mkdir()
    (old / "entry.bib").write_text(brossard)
    store.normalize_library()
    assert not (library / "Brossard2020").exists()
    renamed = library / "brossard2020"
    assert renamed.is_dir()
    assert (renamed / "entry.bib").read_text().startswith("@article{brossard2020,")


def test_list_papers(library):
    store.store_paper(BIB)
    papers = store.list_papers()
    assert len(papers) == 1
    assert papers[0]["key"] == "vaswani2017"
    assert "Attention is All You Need" in papers[0]["title"]
    assert papers[0]["has_pdf"] is False


def test_get_paper(library):
    store.store_paper(BIB)
    paper = store.get_paper("vaswani2017")
    assert paper is not None
    assert paper["title"] == "Attention is All You Need"
    assert store.get_paper("missing") is None


def test_search_index(library):
    store.store_paper(BIB)
    lines = store.search_index()
    assert len(lines) == 1
    assert lines[0].startswith("vaswani2017\t2017 Vaswani, Ashish and Shazeer, Noam and Parmar, Niki — Attention is All You Need")


def test_resolve_paper_url_from_doi(library):
    store.store_paper(BIB)
    assert store.resolve_paper_url(store.get_paper("vaswani2017")) == "https://doi.org/10.48550/arxiv.1706.03762"


def test_resolve_paper_url_prefers_explicit_url(library):
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, url={https://example.org/p}, doi={10.1/x}}")
    assert store.resolve_paper_url(store.get_paper("vaswani2017")) == "https://example.org/p"


def test_resolve_paper_url_missing(library):
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}}")
    with pytest.raises(StoreError):
        store.resolve_paper_url(store.get_paper("vaswani2017"))