# tests/test_monitor.py
import pytest
from bs4 import BeautifulSoup
from datetime import datetime
import requests

import monitor

# фикстура: html со ссылками на PDF
PDF_HTML = """
<html><body>
  <a href="/assets/files/svobodnye-kvartiry/free_flats_01012021.pdf">old</a>
  <a href="/assets/files/svobodnye-kvartiry/free_flats_02022022.pdf">new</a>
</body></html>
"""

# фикстура: html со списком новостей
NEWS_HTML = """
<html><body>
  <div>
    <a href="/novosti/1">Первая новость</a>
  </div>
  <div>
    <a href="/novosti/2">Вторая новость</a>
  </div>
</body></html>
"""

class DummyResp:
    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(f"Status {self.status_code}")

# замокать вызовы session.get
@pytest.fixture(autouse=True)
def mock_session(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.headers = {}
        def get(self, url, *args, **kwargs):
            if monitor.config.PAGE_URL in url:
                return DummyResp(PDF_HTML)
            if monitor.config.NEWS_PAGE_URL in url:
                return DummyResp(NEWS_HTML)
            return DummyResp("", status=404)
    monkeypatch.setattr(monitor, "session", FakeSession())

def test_fetch_latest_pdf():
    fn, url = monitor.fetch_latest_pdf()
    assert fn == "free_flats_02022022.pdf"
    assert url.endswith("/assets/files/svobodnye-kvartiry/free_flats_02022022.pdf")

def test_fetch_latest_news():
    title, url = monitor.fetch_latest_news()
    assert title == "Первая новость" or title == "Вторая новость"
    # по условию берётся первая ссылка в DOM
    assert title == "Первая новость"
    assert url.endswith("/novosti/1")
