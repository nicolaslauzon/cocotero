import argparse

from cocotero import cli, store


def test_get_bibtex_routes_positional_text(monkeypatch):
    monkeypatch.setattr(cli, "_route_paste", lambda text: f"routed:{text}")
    args = argparse.Namespace(
        bib=None, title=None, doi=None, text=["VQF: Highly", "accurate IMU"]
    )
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
    args = argparse.Namespace(
        bib="@article{x, title={T}}", title=None, doi=None, text=None
    )
    assert cli._get_bibtex(args) == "@article{x, title={T}}"


def test_extract_doi():
    assert cli._extract_doi("10.48550/arxiv.1706.03762") == "10.48550/arxiv.1706.03762"
    assert (
        cli._extract_doi("https://doi.org/10.1109/LRA.2020.3003256")
        == "10.1109/LRA.2020.3003256"
    )
    assert (
        cli._extract_doi("see https://doi.org/10.1109/LRA.2020.3003256.")
        == "10.1109/LRA.2020.3003256"
    )
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
    assert (
        cli._route_paste("10.48550/arxiv.1706.03762")
        == "bibtex-10.48550/arxiv.1706.03762"
    )


def test_route_paste_arxiv(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_arxiv", lambda aid: f"bibtex-{aid}")
    assert cli._route_paste("https://arxiv.org/abs/1706.03762") == "bibtex-1706.03762"


def test_route_paste_title(monkeypatch):
    monkeypatch.setattr(cli, "_lookup_by_title", lambda title: "bibtex")
    assert cli._route_paste("Attention Is All You Need") == "bibtex"


def _isolated_library(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))


def test_cmd_browse_cluster_picks_within_cluster(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    store.set_categories("vaswani2017", {"imu"})
    picked = []
    monkeypatch.setattr(
        cli,
        "_fzf_pick_paper",
        lambda category=None: picked.append(category) or "vaswani2017",
    )
    monkeypatch.setattr(cli, "_open_paper_url", lambda key: None)
    cli.cmd_browse_cluster(argparse.Namespace(cluster="imu"))
    assert picked == ["imu"]


def test_cmd_cite_prints_bibtex(tmp_path, monkeypatch, capsys):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    cli.cmd_cite(argparse.Namespace(key="vaswani2017"))
    assert "@article{vaswani2017," in capsys.readouterr().out


def test_cmd_cite_unknown_key_exits(tmp_path, monkeypatch, capsys):
    _isolated_library(tmp_path, monkeypatch)
    try:
        cli.cmd_cite(argparse.Namespace(key="missing"))
    except SystemExit as exc:
        assert exc.code == 1
    assert "No paper with key 'missing'" in capsys.readouterr().out


def test_cmd_cluster_tags_all_papers(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    bib = (
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T1}, doi={10.1/x}}\n"
        "@article{y, author={Brossard, Martin}, year={2020}, title={T2}, doi={10.2/y}}"
    )
    monkeypatch.setattr(cli, "_read_paste", lambda: bib)
    monkeypatch.setattr(
        cli,
        "download_pdf",
        lambda paper, interactive=False: {"source": None, "pdf": None},
    )
    cli.cmd_cluster(argparse.Namespace(category="paper-1", text=[]))
    assert store.categories("vaswani2017") == {"paper-1"}
    assert store.categories("brossard2020") == {"paper-1"}


def test_cmd_clean_dedup(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    (tmp_path / "bib").mkdir()
    kept = tmp_path / "bib" / "vaswani2017.bib"
    kept.write_text(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, "
        "doi={10.1/x}, keywords={dubois2026, robot}}"
    )
    dup = tmp_path / "bib" / "vaswani2017-2.bib"
    dup.write_text(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    cli.cmd_clean(argparse.Namespace(keep=[]))
    bibs = list((tmp_path / "bib").glob("*.bib"))
    assert len(bibs) == 1
    text = kept.read_text()
    assert "category = {dubois2026}" in text
    assert "keywords" not in text


def test_cmd_pdf_links_local_file(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 manual")
    cli.cmd_pdf(argparse.Namespace(key="vaswani2017", path=str(pdf)))
    assert (tmp_path / "pdf" / "vaswani2017.pdf").is_file()
    assert (
        "file = {:pdf/vaswani2017.pdf:PDF}"
        in (tmp_path / "bib" / "vaswani2017.bib").read_text()
    )


def test_cmd_pdf_retry_one(monkeypatch, tmp_path):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    calls = []

    def fake_download(paper, interactive=False):
        calls.append((paper["key"], interactive))
        return {"source": "arxiv", "pdf": "/tmp/paper.pdf"}

    monkeypatch.setattr(cli, "download_pdf", fake_download)
    cli.cmd_pdf(argparse.Namespace(key="vaswani2017", path=None))
    assert calls == [("vaswani2017", False)]


def test_cmd_pdf_retry_all(monkeypatch, tmp_path):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1/x}}"
    )
    store.store_paper(
        "@article{y, author={Brossard, Martin}, year={2020}, title={U}, doi={10.2/y}}"
    )
    calls = []

    def fake_download(paper, interactive=False):
        calls.append(paper["key"])
        return {"source": "arxiv", "pdf": "/tmp/paper.pdf"}

    monkeypatch.setattr(cli, "download_pdf", fake_download)
    cli.cmd_pdf(argparse.Namespace(key=None, path=None))
    assert sorted(calls) == ["brossard2020", "vaswani2017"]


def test_cmd_pdf_retry_all_handoffs_paywalled(tmp_path, monkeypatch):
    _isolated_library(tmp_path, monkeypatch)
    store.store_paper(
        "@article{x, author={Vaswani, Ashish}, year={2017}, title={T}, doi={10.1109/1}}"
    )
    (tmp_path / "config.toml").write_text(
        f'library = "{tmp_path}"\n'
        'unpaywall_email = ""\n'
        'proxy_prefix = "https://ezproxy.ulaval.ca/login?url="\n'
        'downloads_dir = "~/Downloads"\n'
        'handoff_mode = "assisted"\n'
        'pdf_priority = ["arxiv"]\n'
    )
    monkeypatch.setattr(
        cli,
        "download_pdf",
        lambda paper, interactive=False: {"source": None, "pdf": None},
    )
    handed = []
    monkeypatch.setattr(
        cli,
        "handoff_paywalled",
        lambda papers, cfg, mode: (
            handed.append(([paper["key"] for paper in papers], mode)) or (0, {})
        ),
    )
    cli.cmd_pdf(argparse.Namespace(key=None, path=None, handoff="auto"))
    assert handed == [(["vaswani2017"], "auto")]
