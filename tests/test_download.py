import tempfile
from pathlib import Path

import pytest
import requests

from cocotero import download, store
from cocotero.config import load_config


@pytest.fixture()
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


def _stored_paper(library, doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need", url=""):
    bib = (
        "@article{x, author={Vaswani, Ashish}, year={2017}, "
        f"title={{{title}}}, doi={{{doi}}}, url={{{url}}}}}"
    )
    store.store_paper(bib)
    return store.get_paper("vaswani2017")


def _pdf_path() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    handle.write(b"%PDF-1.4 test")
    handle.close()
    return Path(handle.name)


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_download_pdf_via_semanticscholar(library, monkeypatch):
    paper = _stored_paper(library)
    urls = []

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        urls.append(url)
        return FakeResponse(payload={"data": [{"openAccessPdf": {"url": "https://example.org/oa.pdf"}}]})

    monkeypatch.setattr(download.requests, "get", fake_get)
    monkeypatch.setattr(download, "_fetch_pdf", lambda url: _pdf_path())

    outcome = download.download_pdf(paper, interactive=False)
    assert outcome["source"] == "semanticscholar"
    assert (library / "vaswani2017" / "paper.pdf").is_file()
    assert urls == ["https://api.semanticscholar.org/graph/v1/paper/search"]


def test_download_pdf_via_unpaywall(library, monkeypatch):
    paper = _stored_paper(library, doi="10.1109/LRA.2020.3003256", title="Denoising IMU")
    (library / "config.toml").write_text(
        (library / "config.toml").read_text().replace('unpaywall_email = ""', 'unpaywall_email = "t@example.com"')
    )

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        if url.startswith("https://api.semanticscholar.org"):
            return FakeResponse(payload={"data": []})
        assert url == "https://api.unpaywall.org/v2/10.1109/LRA.2020.3003256"
        assert params["email"] == "t@example.com"
        return FakeResponse(payload={"best_oa_location": {"url_for_pdf": "https://example.org/paper.pdf"}})

    monkeypatch.setattr(download.requests, "get", fake_get)
    monkeypatch.setattr(download, "_fetch_pdf", lambda url: _pdf_path())

    outcome = download.download_pdf(paper, interactive=False)
    assert outcome["source"] == "unpaywall"
    assert (library / "vaswani2017" / "paper.pdf").is_file()


def test_download_pdf_via_arxiv_url(library, monkeypatch):
    paper = _stored_paper(library, url="https://arxiv.org/abs/1706.03762")

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        assert url == "https://api.semanticscholar.org/graph/v1/paper/search"
        return FakeResponse(payload={"data": []})

    monkeypatch.setattr(download.requests, "get", fake_get)
    monkeypatch.setattr(download, "_fetch_pdf", lambda url: _pdf_path())

    outcome = download.download_pdf(paper, interactive=False)
    assert outcome["source"] == "arxiv"
    assert (library / "vaswani2017" / "paper.pdf").is_file()


def test_download_pdf_all_sources_fail(library, monkeypatch):
    paper = _stored_paper(library, doi="10.1109/LRA.2020.3003256", title="Denoising IMU")

    def fake_get(url, params=None, headers=None, timeout=None, stream=False):
        return FakeResponse(payload={"data": []})

    monkeypatch.setattr(download.requests, "get", fake_get)

    outcome = download.download_pdf(paper, interactive=False)
    assert outcome == {"source": None, "pdf": None}
    assert not (library / "vaswani2017" / "paper.pdf").exists()


def test_fetch_pdf_accepts_pdf_body(monkeypatch):
    class FakeStream:
        def raise_for_status(self):
            pass

        def iter_content(self, _size):
            yield b"%PDF-1.4 test"

    monkeypatch.setattr(
        download.requests,
        "get",
        lambda url, headers=None, timeout=None, stream=False: FakeStream(),
    )
    path = download._fetch_pdf("https://example.org/oa.pdf")
    assert path is not None
    assert path.read_bytes()[:4] == b"%PDF"
    path.unlink()


def test_fetch_pdf_rejects_non_pdf_body(monkeypatch):
    class FakeStream:
        def raise_for_status(self):
            pass

        def iter_content(self, _size):
            yield b"not a pdf"

    monkeypatch.setattr(
        download.requests,
        "get",
        lambda url, headers=None, timeout=None, stream=False: FakeStream(),
    )
    assert download._fetch_pdf("https://example.org/oa.pdf") is None


def test_ezproxy_handoff_picks_new_download(library, monkeypatch):
    paper = _stored_paper(library, doi="10.1109/LRA.2020.3003256", title="Denoising IMU")
    downloads = library / "downloads"
    downloads.mkdir()
    (library / "config.toml").write_text(
        f'library = "{library}"\n'
        'unpaywall_email = ""\n'
        'proxy_prefix = "https://ezproxy.ulaval.ca/login?url="\n'
        f'downloads_dir = "{downloads}"\n'
        'pdf_priority = ["semanticscholar"]\n'
    )
    opened = []
    monkeypatch.setattr(download, "open_in_browser", lambda url: opened.append(url))
    state = {"calls": 0}

    def fake_sleep(_seconds):
        state["calls"] += 1
        if state["calls"] == 2:
            (downloads / "paper.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(download.time, "sleep", fake_sleep)

    stored = download._ezproxy_handoff(paper, load_config())
    assert stored == str(library / "vaswani2017" / "paper.pdf")
    assert (library / "vaswani2017" / "paper.pdf").is_file()
    assert opened == [
        "https://ezproxy.ulaval.ca/login?url=https://doi.org/10.1109/LRA.2020.3003256"
    ]


def test_download_pdf_interactive_handoff(library, monkeypatch):
    paper = _stored_paper(library, doi="10.1109/LRA.2020.3003256", title="Denoising IMU")
    downloads = library / "downloads"
    downloads.mkdir()
    (library / "config.toml").write_text(
        f'library = "{library}"\n'
        'unpaywall_email = ""\n'
        'proxy_prefix = "https://ezproxy.ulaval.ca/login?url="\n'
        f'downloads_dir = "{downloads}"\n'
        'pdf_priority = ["semanticscholar"]\n'
    )
    monkeypatch.setattr(
        download.requests, "get",
        lambda url, params=None, headers=None, timeout=None, stream=False: FakeResponse(payload={"data": []}),
    )
    monkeypatch.setattr(download, "open_in_browser", lambda url: None)
    state = {"calls": 0}

    def fake_sleep(_seconds):
        state["calls"] += 1
        if state["calls"] == 2:
            (downloads / "paper.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(download.time, "sleep", fake_sleep)

    outcome = download.download_pdf(paper, interactive=True)
    assert outcome["source"] == "ezproxy"
    assert outcome["pdf"] == str(library / "vaswani2017" / "paper.pdf")