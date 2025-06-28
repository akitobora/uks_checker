import os
import re
import json
import logging
import hashlib
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

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0"

# ──────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        st = json.load(open(config.STATE_FILE, "r", encoding="utf-8"))
    else:
        st = {}
    st.setdefault("last_pdf",            None)
    st.setdefault("last_pdf_hash",       None)
    st.setdefault("last_news_url",       None)
    st.setdefault("last_stranica_hash",  None)    # ← новый ключ
    return st

def save_state(st: dict):
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────
def fetch_latest_pdf() -> tuple[str, str] | tuple[None, None]:
    resp = session.get(config.PAGE_URL, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    candidates = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"(free_flats_(\d{8})_?\.pdf)$", a["href"])
        if not m:
            continue

        fname = m.group(1)
        ds    = m.group(2)
        dt = None
        for fmt in ("%Y%m%d", "%d%m%Y"):
            try:
                dt = datetime.strptime(ds, fmt)
                break
            except ValueError:
                continue
        if not dt:
            continue

        url = urljoin(config.BASE_URL, a["href"])
        try:
            head = session.head(url, allow_redirects=True, timeout=5)
            if head.status_code != 200:
                logger.info(f"Кандидат {fname} недоступен (HEAD {head.status_code})")
                continue
        except Exception as e:
            logger.warning(f"Не удалось проверить HEAD {url}: {e}")
            continue

        candidates.append((dt, fname, url))

    if not candidates:
        return None, None
    _, fname, furl = max(candidates, key=lambda x: x[0])
    return fname, furl

def fetch_latest_news() -> tuple[str, str] | tuple[None, None]:
    resp = session.get(config.NEWS_PAGE_URL, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    a = soup.find("a", href=re.compile(r"^/novosti/"))
    if not a:
        return None, None

    title = a.get_text(strip=True)
    url   = urljoin(config.BASE_URL, a["href"])
    return title, url

def fetch_stranica() -> str:
    """
    Скачиваем и возвращаем чистый текст body страницы STRANICA_URL.
    """
    resp = session.get(config.STRANICA_URL, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # получаем только текст внутри тега <body>
    content = soup.body.get_text(separator="\n", strip=True)
    return content

# ──────────────────────────────────────────────────────────
async def scheduled_pdf(context: ContextTypes.DEFAULT_TYPE):
    st        = load_state()
    last_hash = st["last_pdf_hash"]

    fname, furl = fetch_latest_pdf()
    if not fname:
        return

    logger.info(f"Downloading PDF for hash check: {furl}")
    try:
        r = session.get(furl, timeout=15)
        r.raise_for_status()
    except requests.exceptions.HTTPError as err:
        if r.status_code == 404:
            logger.warning(f"PDF ещё не готов (404): {furl}")
            return
        logger.error(f"HTTPError при скачивании {furl}: {err}", exc_info=True)
        return
    except Exception as err:
        logger.error(f"Ошибка при скачивании PDF: {err}", exc_info=True)
        return

    data = r.content
    new_hash = hashlib.sha256(data).hexdigest()
    if new_hash == last_hash:
        logger.info("PDF hash не изменился, пропускаем")
        return

    local = os.path.join("downloads", fname)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    with open(local, "wb") as f:
        f.write(data)

    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text="✅ Вышла новая редакция файла"
    )
    await context.bot.send_document(
        chat_id=config.CHAT_ID,
        document=open(local, "rb")
    )
    logger.info(f"Sent PDF {fname}")

    st["last_pdf_hash"] = new_hash
    st["last_pdf"]      = fname
    save_state(st)

async def scheduled_news(context: ContextTypes.DEFAULT_TYPE):
    st            = load_state()
    last_news_url = st["last_news_url"]

    title, url = fetch_latest_news()
    if not url or url == last_news_url:
        return

    text = f"📰 Новая новость:\n{title}\n{url}"
    await context.bot.send_message(chat_id=config.CHAT_ID, text=text)
    logger.info(f"Sent news {url}")

    st["last_news_url"] = url
    save_state(st)

async def scheduled_stranica(context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяем страницу STRANICA_URL на изменения (через хеш body-текста).
    """
    st         = load_state()
    last_hash  = st["last_stranica_hash"]

    try:
        content = fetch_stranica()
    except Exception as err:
        logger.error(f"Ошибка при fetch_stranica: {err}", exc_info=True)
        return

    new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if new_hash == last_hash:
        return

    # сохраняем новый хеш и шлём уведомление
    st["last_stranica_hash"] = new_hash
    save_state(st)

    await context.bot.send_message(
        chat_id=config.CHAT_ID,
        text=f"ℹ️ Обновления на странице 1:\n{config.STRANICA_URL}"
    )
    logger.info("Отправка инфы по странице")

# ──────────────────────────────────────────────────────────
async def cmd_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    st = load_state()
    await update.message.reply_text(
        f"Текущее состояние:\n```json\n{json.dumps(st, indent=2, ensure_ascii=False)}\n```",
        parse_mode="MarkdownV2"
    )

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Слежу за PDF, новостями и страницей 1.\n"
        "Команды:\n"
        "/getpdf — получить текущий PDF\n"
        "/getnews — получить текущую новость\n"
        "/state — показать сохранённое состояние"
    )
# ──────────────────────────────────────────────────────────
async def cmd_getpdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fname, furl = fetch_latest_pdf()
    if not fname:
        return await update.message.reply_text("PDF не найден.")
    local = os.path.join("downloads", fname)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    r = session.get(furl, stream=True, timeout=15)
    r.raise_for_status()
    with open(local, "wb") as f:
        for chunk in r.iter_content(32_768):
            f.write(chunk)
    await ctx.bot.send_message(chat_id=update.effective_chat.id, text="✅ Текущий PDF:")
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
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception:", exc_info=context.error)

def main():
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    app.add_error_handler(global_error_handler)

    jq = app.job_queue
    jq.run_repeating(scheduled_pdf,
                     interval=config.CHECK_EVERY_MINUTES * 60,
                     first=5)
    jq.run_repeating(scheduled_news,
                     interval=config.NEWS_CHECK_INTERVAL * 60,
                     first=10)
    jq.run_repeating(scheduled_stranica,
                     interval=config.STRANICA_CHECK_INTERVAL * 60,
                     first=15)

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("state",  cmd_state))
    app.add_handler(CommandHandler("getpdf", cmd_getpdf))
    app.add_handler(CommandHandler("getnews",cmd_getnews))

    logger.info("Bot started, polling…")
    app.run_polling()

if __name__ == "__main__":
    main()