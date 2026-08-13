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

BATCH = (
    BIB
    + """
@article{brossard2020,
  author = {Brossard, Martin and Bonnabel, Silvere},
  title = {Denoising IMU},
  year = {2020},
  doi = {10.1109/LRA.2020.3003256}
}"""
)


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
    bib = library / "bib" / f"{result['key']}.bib"
    assert result["key"] == "vaswani2017"
    assert bib.is_file()
    assert not result["pdf"]
    assert bib.read_text().startswith("@article{vaswani2017,")


def test_store_paper_injects_url(library):
    result = store.store_paper(BIB)
    text = (library / "bib" / f"{result['key']}.bib").read_text()
    assert "url = {https://doi.org/10.48550/arxiv.1706.03762}" in text


def test_store_paper_with_pdf(library):
    pdf = library / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    result = store.store_paper(BIB, pdf_path=str(pdf))
    assert result["pdf"] == str(library / "pdf" / "vaswani2017.pdf")
    text = (library / "bib" / f"{result['key']}.bib").read_text()
    assert "file = {:pdf/vaswani2017.pdf:PDF}" in text


def test_store_paper_duplicate_doi(library):
    store.store_paper(BIB)
    second = store.store_paper(BIB.replace("vaswani2017attention", "copy2017"))
    assert second["status"] == "skipped"
    assert second["existing_key"] == "vaswani2017"
    assert len(list((library / "bib").glob("*.bib"))) == 1


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
    second = store.store_paper(
        BIB.replace("10.48550/arxiv.1706.03762", "10.9999/different")
    )
    assert first["status"] == "added"
    assert second["status"] == "added"


def test_store_papers_batch(library):
    results = store.store_papers(BATCH)
    assert [r["status"] for r in results] == ["added", "added"]
    assert len(list((library / "bib").glob("*.bib"))) == 2


def test_store_papers_batch_skips_duplicates(library):
    dup = (
        "@article{vaswani2017copy, author={Vaswani, Ashish}, year={2017}, "
        "title={Attention is All You Need}, doi={10.48550/arxiv.1706.03762}}"
    )
    results = store.store_papers(BATCH + "\n" + dup)
    assert [r["status"] for r in results] == ["added", "added", "skipped"]
    assert len(list((library / "bib").glob("*.bib"))) == 2


def test_store_papers_bad_bibtex(library):
    with pytest.raises(StoreError, match="No BibTeX entries found"):
        store.store_papers("not bibtex at all")


def test_store_papers_recovers_after_broken_entry(library):
    text = (
        "@article{a, author={Vaswani, Ashish}, year={2017}, title={T1}, doi={10.1/a}}\n"
        "@article{b, author={Broken, Bad}, title={unclosed\n"
        "@article{c, author={Brossard, Martin}, year={2020}, title={T3}, doi={10.2/c}}"
    )
    results = store.store_papers(text)
    assert [r["key"] for r in results] == ["vaswani2017", "brossard2020"]
    assert len(list((library / "bib").glob("*.bib"))) == 2


def test_store_papers_broken_only_returns_empty(library):
    text = "@article{b, author={Broken, Bad}, title={unclosed"
    assert store.store_papers(text) == []


def test_store_paper_collision_suffix(library):
    first = store.store_paper(BIB)
    second = store.store_paper(
        BIB.replace("10.48550/arxiv.1706.03762", "10.9999/different")
    )
    assert second["key"] == f"{first['key']}-2"


def test_store_paper_bad_bibtex(library):
    with pytest.raises(StoreError, match="No BibTeX entries found"):
        store.store_paper("@article{broken title={x}")


def test_store_paper_rewrites_key(library):
    result = store.store_paper(BIB.replace("vaswani2017attention", "Brossard2020"))
    assert result["key"] == "vaswani2017"
    assert (library / "bib" / "vaswani2017.bib").is_file()
    assert not (library / "bib" / "Brossard2020.bib").exists()
    assert (
        (library / "bib" / "vaswani2017.bib")
        .read_text()
        .startswith("@article{vaswani2017,")
    )


def test_store_paper_sanitizes_escape_codes(library):
    dirty = "@article{Brossard2020,\n\t\x1bE   author = {Martin Brossard and Silvere Bonnabel},\n\t\x1bE   doi = {10.1109/LRA.2020.3003256},\n\t\x1bE   year = {2020}\n}"
    result = store.store_paper(dirty)
    text = (library / "bib" / f"{result['key']}.bib").read_text()
    assert result["key"] == "brossard2020"
    assert "\x1b" not in text
    assert "author = {Martin Brossard and Silvere Bonnabel}" in text
    assert "doi = {10.1109/LRA.2020.3003256}" in text


def test_normalize_library_renames_old_keys(library):
    brossard = "@article{Brossard2020, author={Brossard, Martin}, year={2020}, title={Denoising IMU}}"
    (library / "bib").mkdir()
    old = library / "bib" / "Brossard2020.bib"
    old.write_text(brossard)
    store.normalize_library()
    assert not (library / "bib" / "Brossard2020.bib").exists()
    renamed = library / "bib" / "brossard2020.bib"
    assert renamed.is_file()
    assert renamed.read_text().startswith("@article{brossard2020,")


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
    assert lines[0].startswith(
        "vaswani2017\t2017 Attention is All You Need — Vaswani, Ashish and Shazeer, Noam and Parmar, Niki"
    )


def test_resolve_paper_url_from_doi(library):
    store.store_paper(BIB)
    assert (
        store.resolve_paper_url(store.get_paper("vaswani2017"))
        == "https://doi.org/10.48550/arxiv.1706.03762"
    )


def test_resolve_paper_url_prefers_explicit_url(library):
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, url={https://example.org/p}, doi={10.1/x}}"
    )
    assert (
        store.resolve_paper_url(store.get_paper("vaswani2017"))
        == "https://example.org/p"
    )


def test_resolve_paper_url_missing(library):
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}}")
    with pytest.raises(StoreError):
        store.resolve_paper_url(store.get_paper("vaswani2017"))


def test_normalize_doi_strips_url_prefix(library):
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, "
        "doi={https://doi.org/10.1109/LRA.2020.3003256}}"
    )
    paper = store.get_paper("vaswani2017")
    assert paper["doi"] == "10.1109/lra.2020.3003256"
    assert (
        store._doi(store._entries((library / "bib" / "vaswani2017.bib").read_text())[0])
        == "10.1109/lra.2020.3003256"
    )


def test_set_doi_injects_url(library):
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}}")
    store.set_doi("vaswani2017", "https://dx.doi.org/10.1109/ICORR.2011.5975346")
    paper = store.get_paper("vaswani2017")
    assert paper["doi"] == "10.1109/icorr.2011.5975346"
    assert paper["url"] == "https://doi.org/10.1109/icorr.2011.5975346"


def test_categories_roundtrip(library):
    result = store.store_paper(BIB)
    assert store.categories(result["key"]) == set()
    store.set_categories(result["key"], {"imu", "deep-learning"})
    assert store.categories(result["key"]) == {"imu", "deep-learning"}
    text = (library / "bib" / f"{result['key']}.bib").read_text()
    assert "category = {deep-learning, imu}" in text
    store.set_categories(result["key"], set())
    assert store.categories(result["key"]) == set()
    assert "category" not in (library / "bib" / f"{result['key']}.bib").read_text()


def test_list_papers_filter_by_category(library):
    store.store_paper(BIB)
    store.set_categories("vaswani2017", {"transformers"})
    assert len(store.list_papers(category="transformers")) == 1
    assert store.list_papers(category="imu") == []


def test_get_paper_includes_categories(library):
    store.store_paper(BIB)
    store.set_categories("vaswani2017", {"attention"})
    assert store.get_paper("vaswani2017")["categories"] == "attention"


def test_store_paper_drops_bibliographic_keywords(library):
    bib = BIB.replace(
        "title={Attention is All You Need}",
        "title={Attention is All You Need}, keywords={transformer, nlp}",
    )
    store.store_paper(bib)
    text = (library / "bib" / "vaswani2017.bib").read_text()
    assert "keywords" not in text
    assert store.categories("vaswani2017") == set()


def test_clean_library_dedup_and_migrate(library):
    (library / "bib").mkdir()
    kept = library / "bib" / "vaswani2017.bib"
    kept.write_text(BIB.replace("}\n}", "},\n  keywords = {dubois2026, robot}\n}"))
    dup = library / "bib" / "vaswani2017-2.bib"
    dup.write_text(BIB.replace("10.48550/arxiv.1706.03762", "10.9999/different"))
    report = store.clean_library(keep_categories={"dubois2026"})
    assert report["removed"] == [("vaswani2017-2", "title")]
    assert report["kept"] == 1
    bibs = list((library / "bib").glob("*.bib"))
    assert len(bibs) == 1
    text = kept.read_text()
    assert "keywords" not in text
    assert "category = {dubois2026}" in text


def test_store_paper_uppercase_fields(library):
    valenti = """@Article{valenti2015,
AUTHOR = {Valenti, Roberto G. and Dryanovski, Ivan and Xiao, Jizhong},
TITLE = {{Keeping a Good Attitude: A Quaternion-Based Orientation Filter for IMUs and MARGs}},
JOURNAL = {Sensors},
YEAR = {2015},
DOI = {10.3390/s150819302}
}"""
    result = store.store_paper(valenti)
    assert result["key"] == "valenti2015"
    assert "Keeping a Good Attitude" in result["title"]
    assert store.find_by_doi(
        store.Path(store.load_config()["library"]), "10.3390/s150819302"
    )


def test_store_papers_dedup_by_doi_ignores_field_case(library):
    store.store_paper(BIB)
    duplicate = BIB.replace("doi = {10.48550", "DOI = {10.48550")
    result = store.store_paper(duplicate)
    assert result["status"] == "skipped"


def test_dedup_existing_uppercase_doi_field(library):
    upper = """@article{dup2020,
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  title = {Attention is All You Need},
  year = {2017},
  DOI = {10.48550/arxiv.1706.03762}
}"""
    store.store_paper(upper)
    result = store.store_paper(BIB)
    assert result["status"] == "skipped"
