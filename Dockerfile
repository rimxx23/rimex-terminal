FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rimex ./rimex
COPY webapp ./webapp

RUN useradd --create-home --uid 1000 rimex && mkdir /app/data && chown rimex /app/data
USER rimex

CMD ["sh", "-c", "exec uvicorn rimex.presentation.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
