# config.py

import os

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = int(os.environ["CHAT_ID"])
PAGE_URL = os.environ.get("PAGE_URL", "https://uksgomel.by/centr-prodazh")
BASE_URL = os.environ.get("BASE_URL", "https://uksgomel.by")
NEWS_PAGE_URL = os.environ.get("NEWS_PAGE_URL", "https://uksgomel.by/novosti")
NEWS_CHECK_INTERVAL = int(os.environ.get("NEWS_CHECK_INTERVAL", 60))  # минут
PATTERN = os.environ.get("PATTERN", r"free_flats_\d{8}\.pdf")
NEWS_LINK_RE = os.environ.get("NEWS_LINK_RE", r"^/novosti/\d+")  # относительный href
CHECK_EVERY_MINUTES = int(os.environ.get("CHECK_EVERY_MINUTES", 30))
STATE_FILE = os.environ.get("STATE_FILE", "last.json")
STRANICA_URL = "https://uksgomel.by/stranica-1"
STRANICA_CHECK_INTERVAL = 60  # в минутах
