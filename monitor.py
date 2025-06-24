# monitor.py

import os
import re
import json
import logging
import requests

from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

import config

# ──────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Сессия для HTTP-запросов
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

# ──────────────────────────────────────────────────────────
def load_state() -> dict:
    """Гарантируем ключи last_pdf и last_news_url."""
    if os.path.exists(config.STATE_FILE):
        st = json.load(open(config.STATE_FILE, "r", encoding="utf-8"))
    else:
        st = {}
    st.setdefault("last_pdf", None)
    st.setdefault("last_news_url", None)
    return st

def save_state(st: dict):
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────
def fetch_latest_pdf() -> tuple[str, str] | tuple[None, None]:
    resp = session.get(config.PAGE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    candidates = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"(free_flats_(\d{8})\.pdf)$", a["href"])
        if not m:
            continue
        fn   = m.group(1)
        ds   = m.group(2)
        # парсим дату
        dt = None
        for fmt in ("%Y%m%d","%d%m%Y"):
            try:
                dt = datetime.strptime(ds, fmt)
                break
            except ValueError:
                continue
        if not dt:
            continue
        url = urljoin(config.BASE_URL, a["href"])
        candidates.append((dt, fn, url))

    if not candidates:
        return None, None
    # самая свежая по дате
    _, fname, furl = max(candidates, key=lambda x: x[0])
    return fname, furl

def fetch_latest_news() -> tuple[str, str] | tuple[None, None]:
    """
    Возвращает (title, absolute_url) первой новости
    на странице с новостями (самая свежая сверху).
    """
    resp = session.get(config.NEWS_PAGE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    a = soup.find("a", href=re.compile(r"^/novosti/"))
    if not a:
        return None, None

    title = a.get_text(strip=True)
    url   = urljoin(config.BASE_URL, a["href"])
    return title, url

# ──────────────────────────────────────────────────────────
async def scheduled_pdf(context: ContextTypes.DEFAULT_TYPE):
    st       = load_state()
    last_pdf = st["last_pdf"]

    fname, furl = fetch_latest_pdf()
    if not fname or fname == last_pdf:
        return

    # скачать
    local = os.path.join("downloads", fname)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    logger.info(f"Downloading PDF {furl}")
    r = session.get(furl, stream=True)
    r.raise_for_status()
    with open(local, "wb") as f:
        for chunk in r.iter_content(32_768):
            f.write(chunk)

    # уведомление + PDF
    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text="✅ Вышла новая редакция файла"
    )
    await context.bot.send_document(
        chat_id=config.CHAT_ID,
        document=open(local, "rb")
    )
    logger.info(f"Sent PDF {fname}")

    st["last_pdf"] = fname
    save_state(st)

async def scheduled_news(context: ContextTypes.DEFAULT_TYPE):
    st           = load_state()
    last_news_url = st["last_news_url"]

    title, url = fetch_latest_news()
    if not url or url == last_news_url:
        return

    text = f"📰 Новая новость:\n{title}\n{url}"
    await context.bot.send_message(chat_id=config.CHAT_ID, text=text)
    logger.info(f"Sent news {url}")

    st["last_news_url"] = url
    save_state(st)

# ──────────────────────────────────────────────────────────
async def cmd_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    st = load_state()
    await update.message.reply_text(
        f"Текущее состояние:\n```json\n{json.dumps(st, indent=2, ensure_ascii=False)}\n```",
        parse_mode="MarkdownV2"
    )

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Слежу за PDF и новостями.\n"
        "Команды:\n"
        "/getpdf — получить текущий PDF\n"
        "/getnews — получить текущую новость\n"
        "/state — показать сохранённое состояние"
    )

async def cmd_getpdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fname, furl = fetch_latest_pdf()
    if not fname:
        return await update.message.reply_text("PDF не найден.")
    local = os.path.join("downloads", fname)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    r = session.get(furl, stream=True)
    r.raise_for_status()
    with open(local, "wb") as f:
        for chunk in r.iter_content(32_768):
            f.write(chunk)
    await ctx.bot.send_message(chat_id=update.effective_chat.id,
                               text="✅ Текущий PDF:")
    await ctx.bot.send_document(chat_id=update.effective_chat.id,
                                document=open(local, "rb"))

async def cmd_getnews(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title, url = fetch_latest_news()
    if not url:
        return await update.message.reply_text("Новостей не найдено.")
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📰 Текущая новость:\n{title}\n{url}"
    )

# ──────────────────────────────────────────────────────────
def main():
    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .build()
    )

    jq = app.job_queue
    # расписание для PDF и новостей
    jq.run_repeating(scheduled_pdf,
                     interval=config.CHECK_EVERY_MINUTES * 60,
                     first=5)
    jq.run_repeating(scheduled_news,
                     interval=config.NEWS_CHECK_INTERVAL * 60,
                     first=10)

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("state",  cmd_state))
    app.add_handler(CommandHandler("getpdf", cmd_getpdf))
    app.add_handler(CommandHandler("getnews",cmd_getnews))

    logger.info("Bot started, polling…")
    app.run_polling()

if __name__ == "__main__":
    main()
