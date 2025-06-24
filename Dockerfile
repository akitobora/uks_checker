FROM python:3.11-slim

WORKDIR /app

# копируем и ставим зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копируем весь код
COPY . .

# папка для скачанных файлов
RUN mkdir downloads

# точка входа
CMD ["python", "monitor.py"]
