import pytest
import requests
from urllib.parse import urljoin
from uks_checker.monitor import fetch_latest_pdf, fetch_latest_news, fetch_stranica, session
from uks_checker.monitor import config


class DummyResponse:
    def __init__(
        self, *, text: str = "", content: bytes = None, status_code: int = 200
    ):
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.status_code = status_code

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise requests.HTTPError(f"{self.status_code} Error")


@pytest.fixture(autouse=True)
def fix_config(monkeypatch: pytest.MonkeyPatch):
    """Подменяем URL-ы на фиктивные, чтобы не ходить в интернет"""
    monkeypatch.setattr(config, "PAGE_URL", "http://dummy/pdf-page")
    monkeypatch.setattr(config, "BASE_URL", "http://base")
    monkeypatch.setattr(config, "NEWS_PAGE_URL", "http://dummy/news-page")
    monkeypatch.setattr(config, "STRANICA_URL", "http://dummy/stranica")
    yield


def test_fetch_latest_pdf_picks_newest_and_skips_404(monkeypatch: pytest.MonkeyPatch):
    html = """
    <html><body>
      <a href="/files/free_flats_01012020.pdf">old</a>
      <a href="/files/free_flats_02022020_.pdf">new</a>
      <a href="/files/not_a_match.txt">nope</a>
    </body></html>
    """
    # Подменяем GET страницы
    monkeypatch.setattr(
        session, "get", lambda url, **kw: DummyResponse(text=html, status_code=200)
    )

    # Подменяем HEAD: первый — 404, второй — 200
    def fake_head(url, **kw):
        if "01012020" in url:
            return DummyResponse(status_code=404)
        return DummyResponse(status_code=200)

    monkeypatch.setattr(session, "head", fake_head)

    name, url = fetch_latest_pdf()
    # должна выбрать второй: 02.02.2020 → free_flats_02022020_.pdf
    assert name == "free_flats_02022020_.pdf"
    assert url == urljoin(config.BASE_URL, "/files/free_flats_02022020_.pdf")


def test_fetch_latest_pdf_all_404_returns_none(monkeypatch: pytest.MonkeyPatch):
    html = """
    <html><body>
      <a href="/files/free_flats_01012020.pdf">only</a>
    </body></html>
    """
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))
    monkeypatch.setattr(
        session, "head", lambda *args, **kw: DummyResponse(status_code=404)
    )

    name, url = fetch_latest_pdf()
    assert name is None and url is None


def test_fetch_latest_pdf_no_matches(monkeypatch: pytest.MonkeyPatch):
    html = "<html><body><a href='/foo/bar.txt'>foo</a></body></html>"
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))

    name, url = fetch_latest_pdf()
    assert name is None and url is None


def test_fetch_latest_news_success(monkeypatch: pytest.MonkeyPatch):
    html = """
    <html><body>
      <a href="/novosti/123">Заголовок новости</a>
    </body></html>
    """
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))

    title, url = fetch_latest_news()
    assert title == "Заголовок новости"
    assert url == urljoin(config.BASE_URL, "/novosti/123")


def test_fetch_latest_news_no_link(monkeypatch: pytest.MonkeyPatch):
    html = "<html><body><p>Нет новостей</p></body></html>"
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))

    title, url = fetch_latest_news()
    assert title is None and url is None


def test_fetch_stranica_returns_body_text(monkeypatch: pytest.MonkeyPatch):
    html = """
      <html>
        <head><title>Test</title></head>
        <body>
          <h1>Заголовок</h1>
          <p>Немного текста.</p>
        </body>
      </html>
    """
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))
    text = fetch_stranica()
    # ожидаем объединённый по строкам body-контент
    assert "Заголовок" in text
    assert "Немного текста." in text
    assert "\n" in text  # между блоками есть разделитель


def test_date_parsing_variants(monkeypatch: pytest.MonkeyPatch):
    # Проверяем обе формы YYYYMMDD и DDMMYYYY
    html = """
    <html><body>
      <a href="/files/free_flats_20230115.pdf">a</a>
      <a href="/files/free_flats_15012023_.pdf">b</a>
    </body></html>
    """
    monkeypatch.setattr(session, "get", lambda *args, **kw: DummyResponse(text=html))
    # оба HEAD = 200, поэтому выберем max по дате (они равны — тогда последний в списке)
    monkeypatch.setattr(
        session, "head", lambda *args, **kw: DummyResponse(status_code=200)
    )

    name, url = fetch_latest_pdf()
    assert name in ("free_flats_20230115.pdf", "free_flats_15012023_.pdf")
    assert url.startswith(config.BASE_URL)
