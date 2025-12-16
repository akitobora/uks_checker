# config.py

import os
import logging

logger = logging.getLogger(__name__)

def _get_env(key: str, default: str | None = None, required: bool = False) -> str:
    """Безопасное получение переменной окружения с валидацией."""
    value = os.environ.get(key, default)
    if required and not value:
        raise ValueError(f"Обязательная переменная окружения {key} не установлена")
    return value

def _get_int_env(key: str, default: int) -> int:
    """Получение целочисленной переменной окружения."""
    try:
        return int(os.environ.get(key, str(default)))
    except ValueError:
        logger.warning(f"Неверное значение для {key}, используется значение по умолчанию: {default}")
        return default

# Обязательные переменные
BOT_TOKEN            = _get_env("BOT_TOKEN", required=True)
CHAT_ID              = int(_get_env("CHAT_ID", required=True))

# Опциональные переменные с значениями по умолчанию
PAGE_URL             = _get_env("PAGE_URL", "https://uksgomel.by/centr-prodazh")
BASE_URL             = _get_env("BASE_URL", "https://uksgomel.by")
NEWS_PAGE_URL        = _get_env("NEWS_PAGE_URL", "https://uksgomel.by/novosti")
NEWS_CHECK_INTERVAL  = _get_int_env("NEWS_CHECK_INTERVAL", 60)  # минут
PATTERN              = _get_env("PATTERN", r"free_flats_\d{8}\.pdf")
NEWS_LINK_RE         = _get_env("NEWS_LINK_RE", r"^/novosti/\d+")
CHECK_EVERY_MINUTES  = _get_int_env("CHECK_EVERY_MINUTES", 30)
STATE_FILE           = _get_env("STATE_FILE", "state/last.json")
STRANICA_URL         = _get_env("STRANICA_URL", "https://uksgomel.by/stranica-1")
STRANICA_CHECK_INTERVAL = _get_int_env("STRANICA_CHECK_INTERVAL", 60)  # в минутах

# Максимальный размер файла для отправки в Telegram (50MB - лимит Telegram)
MAX_FILE_SIZE_MB = _get_int_env("MAX_FILE_SIZE_MB", 50)
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

def validate_config():
    """Валидация конфигурации при старте приложения."""
    errors = []
    
    if not BOT_TOKEN or len(BOT_TOKEN) < 10:
        errors.append("BOT_TOKEN должен быть валидным токеном Telegram бота")
    
    if not isinstance(CHAT_ID, int) or CHAT_ID == 0:
        errors.append("CHAT_ID должен быть валидным числовым ID чата")
    
    if CHECK_EVERY_MINUTES < 1:
        errors.append("CHECK_EVERY_MINUTES должен быть >= 1")
    
    if NEWS_CHECK_INTERVAL < 1:
        errors.append("NEWS_CHECK_INTERVAL должен быть >= 1")
    
    if STRANICA_CHECK_INTERVAL < 1:
        errors.append("STRANICA_CHECK_INTERVAL должен быть >= 1")
    
    if MAX_FILE_SIZE_MB < 1 or MAX_FILE_SIZE_MB > 50:
        errors.append("MAX_FILE_SIZE_MB должен быть от 1 до 50")
    
    if errors:
        error_msg = "Ошибки конфигурации:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)
    
    logger.info("Конфигурация валидирована успешно")