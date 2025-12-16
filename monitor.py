import os
import re
import json
import logging
import hashlib
import signal
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
# Настройка логирования
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get("LOG_FORMAT", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")

logging.basicConfig(
    format=LOG_FORMAT,
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Оптимизированная сессия с retry стратегией и connection pooling
session = requests.Session()

# Настройка retry стратегии
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)

adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=10,
    pool_maxsize=10
)

session.mount("http://", adapter)
session.mount("https://", adapter)
session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; UKS-Checker/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive"
})

# ──────────────────────────────────────────────────────────
# Кэш состояния для уменьшения I/O операций
_state_cache: dict | None = None
_state_file_lock = False

def load_state() -> dict:
    """Загружает состояние из файла с кэшированием."""
    global _state_cache
    
    if _state_cache is not None:
        return _state_cache
    
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Ошибка при чтении состояния: {e}, используем пустое состояние")
            st = {}
    else:
        st = {}
    
    st.setdefault("last_pdf",            None)
    st.setdefault("last_pdf_hash",       None)
    st.setdefault("last_news_url",       None)
    st.setdefault("last_stranica_hash",  None)
    
    _state_cache = st
    return st

def save_state(st: dict):
    """Сохраняет состояние в файл атомарно."""
    global _state_cache, _state_file_lock
    
    if _state_file_lock:
        logger.warning("Попытка сохранения состояния во время другой операции")
        return
    
    _state_file_lock = True
    try:
        # Атомарная запись через временный файл
        temp_file = config.STATE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, config.STATE_FILE)
        _state_cache = st.copy()
    except IOError as e:
        logger.error(f"Ошибка при сохранении состояния: {e}", exc_info=True)
    finally:
        _state_file_lock = False

# ──────────────────────────────────────────────────────────
def fetch_latest_pdf() -> tuple[str, str] | tuple[None, None]:
    """Находит последний PDF файл. Оптимизировано: убраны лишние HEAD запросы."""
    try:
        resp = session.get(config.PAGE_URL, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при загрузке страницы {config.PAGE_URL}: {e}")
        return None, None
    
    soup = BeautifulSoup(resp.text, "html.parser")
    candidates = []
    
    # Предкомпилируем регулярное выражение для производительности
    pdf_pattern = re.compile(r"(free_flats_(\d{8})_?\.pdf)$")
    date_formats = ("%Y%m%d", "%d%m%Y")
    
    for a in soup.find_all("a", href=True):
        m = pdf_pattern.search(a["href"])
        if not m:
            continue

        fname = m.group(1)
        ds = m.group(2)
        dt = None
        
        for fmt in date_formats:
            try:
                dt = datetime.strptime(ds, fmt)
                break
            except ValueError:
                continue
        
        if not dt:
            continue

        url = urljoin(config.BASE_URL, a["href"])
        candidates.append((dt, fname, url))

    if not candidates:
        return None, None
    
    # Находим самый свежий файл по дате
    _, fname, furl = max(candidates, key=lambda x: x[0])
    return fname, furl

def fetch_latest_news() -> tuple[str, str] | tuple[None, None]:
    """Получает последнюю новость с сайта."""
    try:
        resp = session.get(config.NEWS_PAGE_URL, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при загрузке новостей {config.NEWS_PAGE_URL}: {e}")
        return None, None
    
    soup = BeautifulSoup(resp.text, "html.parser")
    # Предкомпилируем регулярное выражение
    news_pattern = re.compile(r"^/novosti/")
    a = soup.find("a", href=news_pattern)
    
    if not a:
        return None, None

    title = a.get_text(strip=True)
    url = urljoin(config.BASE_URL, a["href"])
    return title, url

def fetch_stranica() -> str:
    """
    Скачиваем и возвращаем чистый текст body страницы STRANICA_URL.
    """
    try:
        resp = session.get(config.STRANICA_URL, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка при загрузке страницы {config.STRANICA_URL}: {e}")
        raise
    
    soup = BeautifulSoup(resp.text, "html.parser")
    # получаем только текст внутри тега <body>
    if soup.body is None:
        logger.warning(f"Тег <body> не найден на странице {config.STRANICA_URL}")
        return ""
    
    content = soup.body.get_text(separator="\n", strip=True)
    return content

# ──────────────────────────────────────────────────────────
async def scheduled_pdf(context: ContextTypes.DEFAULT_TYPE):
    """Планируемая задача проверки PDF файлов."""
    try:
        st        = load_state()
        last_hash = st["last_pdf_hash"]

        fname, furl = fetch_latest_pdf()
        if not fname:
            logger.debug("PDF файлы не найдены")
            return

        logger.info(f"Downloading PDF for hash check: {furl}")
        try:
            r = session.get(furl, timeout=15)
            r.raise_for_status()
        except requests.exceptions.HTTPError as err:
            status_code = getattr(err.response, 'status_code', None)
            if status_code == 404:
                logger.warning(f"PDF ещё не готов (404): {furl}")
                return
            logger.error(f"HTTPError при скачивании {furl}: {err}", exc_info=True)
            return
        except requests.exceptions.RequestException as err:
            logger.error(f"Ошибка сети при скачивании PDF {furl}: {err}", exc_info=True)
            return
        except Exception as err:
            logger.error(f"Неожиданная ошибка при скачивании PDF: {err}", exc_info=True)
            return

        data = r.content
        file_size = len(data)
        
        # Проверяем размер файла
        if file_size > config.MAX_FILE_SIZE:
            logger.warning(f"PDF файл слишком большой ({file_size / 1024 / 1024:.2f} MB), пропускаем отправку")
            await context.bot.send_message(
                chat_id=config.CHAT_ID,
                text=f"⚠️ Обнаружен новый PDF, но файл слишком большой ({file_size / 1024 / 1024:.2f} MB)\n"
                     f"Максимальный размер: {config.MAX_FILE_SIZE_MB} MB\n"
                     f"URL: {furl}"
            )
            return
        
        new_hash = hashlib.sha256(data).hexdigest()
        if new_hash == last_hash:
            logger.info("PDF hash не изменился, пропускаем")
            return

        local = os.path.join("downloads", fname)
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as f:
            f.write(data)

        try:
            await context.bot.send_message(
                chat_id=config.CHAT_ID,
                text=f"✅ Вышла новая редакция файла\nРазмер: {file_size / 1024 / 1024:.2f} MB"
            )
            
            # Используем контекстный менеджер для файла
            with open(local, "rb") as pdf_file:
                await context.bot.send_document(
                    chat_id=config.CHAT_ID,
                    document=pdf_file,
                    filename=fname
                )
            logger.info(f"Sent PDF {fname} ({file_size / 1024 / 1024:.2f} MB)")
            
            st["last_pdf_hash"] = new_hash
            st["last_pdf"]      = fname
            save_state(st)
        except Exception as e:
            logger.error(f"Ошибка при отправке PDF в Telegram: {e}", exc_info=True)
            # Не сохраняем состояние, чтобы попробовать отправить снова при следующей проверке
            return
    except Exception as e:
        logger.error(f"Критическая ошибка в scheduled_pdf: {e}", exc_info=True)

async def scheduled_news(context: ContextTypes.DEFAULT_TYPE):
    """Планируемая задача проверки новостей."""
    try:
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
    except Exception as e:
        logger.error(f"Критическая ошибка в scheduled_news: {e}", exc_info=True)

async def scheduled_stranica(context: ContextTypes.DEFAULT_TYPE):
    """
    Проверяем страницу STRANICA_URL на изменения (через хеш body-текста).
    """
    try:
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
    except Exception as e:
        logger.error(f"Критическая ошибка в scheduled_stranica: {e}", exc_info=True)

# ──────────────────────────────────────────────────────────
async def cmd_state(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показывает текущее состояние бота."""
    st = load_state()
    # Экранируем специальные символы MarkdownV2
    state_json = json.dumps(st, indent=2, ensure_ascii=False)
    # Экранируем специальные символы для MarkdownV2
    escaped_json = state_json.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("]", "\\]")
    await update.message.reply_text(
        f"Текущее состояние:\n```json\n{escaped_json}\n```",
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
    try:
        r = session.get(furl, stream=True, timeout=15)
        r.raise_for_status()
        with open(local, "wb") as f:
            for chunk in r.iter_content(32_768):
                f.write(chunk)
        await ctx.bot.send_message(chat_id=update.effective_chat.id, text="✅ Текущий PDF:")
        with open(local, "rb") as pdf_file:
            await ctx.bot.send_document(chat_id=update.effective_chat.id, document=pdf_file)
    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при получении PDF: {err}", exc_info=True)
        await update.message.reply_text(f"❌ Ошибка при загрузке PDF: {err}")
    except Exception as err:
        logger.error(f"Неожиданная ошибка в cmd_getpdf: {err}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при обработке запроса.")

async def cmd_getnews(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    title, url = fetch_latest_news()
    if not url:
        return await update.message.reply_text("Новостей не найдено.")
    await ctx.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📰 Текущая новость:\n{title}\n{url}"
    )

# ──────────────────────────────────────────────────────────
# Глобальные переменные для graceful shutdown
_app_instance = None
_shutdown_event = None

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик ошибок."""
    logger.error("Unhandled exception:", exc_info=context.error)
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке команды. Попробуйте позже."
            )
        except Exception:
            pass  # Игнорируем ошибки при отправке сообщения об ошибке

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown."""
    logger.info(f"Получен сигнал {signum}, начинаем graceful shutdown...")
    if _app_instance:
        _app_instance.stop()
    sys.exit(0)

async def check_telegram_connection(app):
    """Проверяет доступность Telegram API при старте."""
    try:
        bot_info = await app.bot.get_me()
        logger.info(f"Подключение к Telegram API успешно. Бот: @{bot_info.username}")
        return True
    except Exception as e:
        logger.error(f"Не удалось подключиться к Telegram API: {e}")
        return False

def main():
    global _app_instance
    
    # Валидация конфигурации
    try:
        config.validate_config()
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        sys.exit(1)
    
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    app = ApplicationBuilder().token(config.BOT_TOKEN).build()
    _app_instance = app
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
    app.add_handler(CommandHandler("getnews", cmd_getnews))

    # Проверка подключения к Telegram перед запуском
    async def startup_check(ctx: ContextTypes.DEFAULT_TYPE):
        try:
            if not await check_telegram_connection(app):
                logger.error("Не удалось подключиться к Telegram API. Завершение работы.")
                sys.exit(1)
            logger.info("Bot started, polling…")
        except Exception as e:
            logger.error(f"Ошибка при проверке подключения: {e}", exc_info=True)
            sys.exit(1)
    
    # Запускаем проверку при старте (через 2 секунды после запуска)
    app.job_queue.run_once(startup_check, when=2)
    
    """
    app.run_webhook(
    listen="0.0.0.0",
    port=8080,
    webhook_url="https://bba7ujaae80r5nogivh1.containers.yandexcloud.net/"
    )
    """
    try:
        app.run_polling(drop_pending_updates=True)
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания, завершение работы...")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Бот остановлен")

if __name__ == "__main__":
    main()
