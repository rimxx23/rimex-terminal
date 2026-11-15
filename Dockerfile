FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scanner.py bot.py middlewares.py ratelimit.py api.py ./
COPY webapp ./webapp

RUN useradd --create-home --uid 1000 rimex
USER rimex

CMD ["python", "bot.py"]
