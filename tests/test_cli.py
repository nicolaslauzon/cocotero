import argparse

from cocotero import cli, store


def test_get_bibtex_routes_positional_text(monkeypatch):
    monkeypatch.setattr(cli, "_route_paste", lambda text: f"routed:{text}")
    args = argparse.Namespace(bib=None, title=None, doi=None, text=["VQF: Highly", "accurate IMU"])
    assert cli._get_bibtex(args) == "routed:VQF: Highly accurate IMU"


def test_get_bibtex_joins_multiword_positional(monkeypatch):
    monkeypatch.setattr(cli, "_route_paste", lambda text: f"routed:{text}")
    args = argparse.Namespace(
        bib=None, title=None, doi=None, text=["attention", "is", "all", "you", "need"]
    )
    assert cli._get_bibtex(args) == "routed:attention is all you need"


def test_get_bibtex_empty_positional_falls_back_to_paste(monkeypatch):
    monkeypatch.setattr(cli, "_route_paste", lambda text: f"paste:{text}")
    monkeypatch.setattr(cli, "_read_paste", lambda: "pasted text")
    args = argparse.Namespace(bib=None, title=None, doi=None, text=[])
    assert cli._get_bibtex(args) == "paste:pasted text"


def test_get_bibtex_prefers_explicit_flags(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_doi", lambda doi: f"doi:{doi}")
    args = argparse.Namespace(bib=None, title=None, doi="10.1/x", text="ignored")
    assert cli._get_bibtex(args) == "doi:10.1/x"


def test_get_bibtex_bib_flag(monkeypatch):
    monkeypatch.setattr(cli, "_route_paste", lambda text: "should-not-run")
    args = argparse.Namespace(bib="@article{x, title={T}}", title=None, doi=None, text=None)
    assert cli._get_bibtex(args) == "@article{x, title={T}}"


def test_extract_doi():
    assert cli._extract_doi("10.48550/arxiv.1706.03762") == "10.48550/arxiv.1706.03762"
    assert cli._extract_doi("https://doi.org/10.1109/LRA.2020.3003256") == "10.1109/LRA.2020.3003256"
    assert cli._extract_doi("see https://doi.org/10.1109/LRA.2020.3003256.") == "10.1109/LRA.2020.3003256"
    assert cli._extract_doi("Attention is all you need") is None
    assert cli._extract_doi("") is None


def test_extract_arxiv():
    assert cli._extract_arxiv("https://arxiv.org/abs/1706.03762") == "1706.03762"
    assert cli._extract_arxiv("https://arxiv.org/pdf/2108.09355") == "2108.09355"
    assert cli._extract_arxiv("Attention is all you need") is None


def test_route_paste_bibtex():
    bib = "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}}"
    assert cli._route_paste(f"\n  {bib}\n") == bib


def test_route_paste_empty():
    assert cli._route_paste("") == ""


def test_route_paste_doi(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_doi", lambda doi: f"bibtex-{doi}")
    assert cli._route_paste("10.48550/arxiv.1706.03762") == "bibtex-10.48550/arxiv.1706.03762"


def test_route_paste_arxiv(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_arxiv", lambda aid: f"bibtex-{aid}")
    assert cli._route_paste("https://arxiv.org/abs/1706.03762") == "bibtex-1706.03762"


def test_route_paste_title(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_title", lambda title: "bibtex")
    assert cli._route_paste("Attention Is All You Need") == "bibtex"


def _isolated_library(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))


def test_cmd_cat_toggle(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}")
    args = argparse.Namespace(key="vaswani2017", cat="imu")
    cli.cmd_cat(args)
    assert store.keywords("vaswani2017") == {"imu"}
    cli.cmd_cat(args)
    assert store.keywords("vaswani2017") == set()


def test_cmd_cat_shows_tags(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper("@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}")
    store.set_keywords("vaswani2017", {"imu", "slam"})
    cli.cmd_cat(argparse.Namespace(key="vaswani2017", cat=None))
    assert store.keywords("vaswani2017") == {"imu", "slam"}


def test_cmd_cluster_tags_all_papers(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    bib = (
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T1}, doi={10.1/x}}\n"
        "@article{y, author={Brossard, Martin}, year={2020}, title={T2}, doi={10.2/y}}"
    )
    monkeypatch.setattr(cli, "_read_paste", lambda: bib)
    cli.cmd_cluster(argparse.Namespace(category="paper-1", text=[]))
    assert store.keywords("vaswani2017") == {"paper-1"}
    assert store.keywords("brossard2020") == {"paper-1"}