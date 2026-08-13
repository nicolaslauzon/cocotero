import pytest
import requests

from cocotero import citations, config


@pytest.fixture()
def library(tmp_path, monkeypatch):
    monkeypatch.setenv("COCOTERO_LIB", str(tmp_path))
    monkeypatch.setenv("COCOTERO_CONFIG", str(tmp_path / "config.toml"))
    return tmp_path


class FakeResponse:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._payload


def test_user_agent_no_email(library):
    headers = config.user_agent()
    assert "Cocotero/0.1" in headers["User-Agent"]
    assert "mailto:" not in headers["User-Agent"]


SAMPLE_ITEM = {
    "DOI": "10.48550/arxiv.1706.03762",
    "title": ["Attention Is All You Need"],
    "author": [
        {"family": "Vaswani", "given": "Ashish"},
        {"family": "Shazeer", "given": "Noam"},
    ],
    "issued": {"date-parts": [[2017, 6, 12]]},
    "container-title": ["ArXiv"],
}


def test_search_by_title(library, monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == "https://api.crossref.org/works"
        assert params["query.bibliographic"] == "attention is all you need"
        return FakeResponse(payload={"message": {"items": [SAMPLE_ITEM]}})

    monkeypatch.setattr(citations.requests, "get", fake_get)
    hits = citations.search_by_title("attention is all you need")
    assert len(hits) == 1
    assert hits[0]["doi"] == "10.48550/arxiv.1706.03762"
    assert hits[0]["title"] == "Attention Is All You Need"
    assert hits[0]["authors"] == "Vaswani, Ashish and Shazeer, Noam"
    assert hits[0]["year"] == "2017"


def test_search_by_title_network_error(library, monkeypatch):
    def boom(url, params=None, headers=None, timeout=None):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(citations.requests, "get", boom)
    with pytest.raises(citations.CrossrefError, match="Crossref search failed"):
        citations.search_by_title("x")


def test_search_by_title_bad_json(library, monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(payload={"message": {}})

    monkeypatch.setattr(citations.requests, "get", fake_get)
    with pytest.raises(citations.CrossrefError):
        citations.search_by_title("x")


def test_fetch_bibtex(library, monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        assert url == "https://doi.org/10.48550/arxiv.1706.03762"
        assert "application/x-bibtex" in headers["Accept"]
        return FakeResponse(text="@article{Vaswani2017,\n  author = {Vaswani, Ashish}\n}")

    monkeypatch.setattr(citations.requests, "get", fake_get)
    assert "Vaswani" in citations.fetch_bibtex("10.48550/arxiv.1706.03762")


def test_fetch_bibtex_empty(library, monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(text="")

    monkeypatch.setattr(citations.requests, "get", fake_get)
    with pytest.raises(citations.CrossrefError, match="No BibTeX returned"):
        citations.fetch_bibtex("10.48550/arxiv.1706.03762")


ARXIV_XML = """<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762</id>
    <title>  Attention Is All You Need
</title>
    <published>2017-06-12T17:46:03Z</published>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
  </entry>
</feed>"""


def test_fetch_bibtex_from_arxiv(library, monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == "https://export.arxiv.org/api/query"
        assert params["id_list"] == "1706.03762"
        return FakeResponse(text=ARXIV_XML)

    monkeypatch.setattr(citations.requests, "get", fake_get)
    bib = citations.fetch_bibtex_from_arxiv("1706.03762")
    assert "Attention Is All You Need" in bib
    assert "Ashish Vaswani and Noam Shazeer" in bib
    assert "year = {2017}" in bib
    assert "https://arxiv.org/abs/1706.03762" in bib


def test_fetch_bibtex_from_arxiv_missing(library, monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        return FakeResponse(text='<feed xmlns="http://www.w3.org/2005/Atom"></feed>')

    monkeypatch.setattr(citations.requests, "get", fake_get)
    with pytest.raises(citations.CrossrefError, match="No arXiv entry"):
        citations.fetch_bibtex_from_arxiv("9999.99999")
