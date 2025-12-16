FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости только если нужны
# (для python-telegram-bot и requests они не требуются)

# Копируем и устанавливаем зависимости отдельным слоем
# для лучшего кэширования Docker
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY *.py ./
COPY __init__.py* ./

# Создаем необходимые директории
RUN mkdir -p downloads state

# Копируем healthcheck скрипт
COPY healthcheck.py .
RUN chmod +x healthcheck.py

# Используем python -u для unbuffered output (лучше для логов в Docker)
CMD ["python", "-u", "monitor.py"]

# Health check для Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python healthcheck.py || exit 1
