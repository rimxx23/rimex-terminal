# Rimex Terminal

[![tests](https://github.com/rimxx23/rimex-terminal/actions/workflows/tests.yml/badge.svg)](https://github.com/rimxx23/rimex-terminal/actions/workflows/tests.yml)

Fast anti-scam scanner for Solana tokens. Send a contract address — get a security card in under a second.

Available as a CLI tool, a Telegram bot ([@rimexscanner_bot](https://t.me/rimexscanner_bot)) and a Telegram Mini App.

## Architecture

```
Telegram Mini App (webapp/index.html)
        │  POST /api/scan  + X-Telegram-Init-Data
        ▼
FastAPI (api.py) ──┐
Telegram bot (bot.py) ──┤──► scanner.py ──► DexScreener / Solana RPC / RugCheck
CLI (scanner.py) ──┘
```

One scanning core, three interfaces.

In production the bot does not scan in chat: it replies with an **Open in X-Ray** button that opens the Mini App with the token. Market data APIs rate-limit shared hosting IPs, so the Mini App fills missing market and holder data directly from the user's device.

## What it checks

| Check | Source | Why it matters |
|---|---|---|
| Price, liquidity, 24h volume | DexScreener, fallback GeckoTerminal | Market data; GeckoTerminal is used when DexScreener is rate-limited or has no pairs |
| Mint Authority | Solana RPC | If enabled, the owner can print unlimited tokens |
| Freeze Authority | Solana RPC | If enabled, the owner can freeze your tokens |
| LP locked % | RugCheck | Unlocked liquidity can be pulled (rug pull) |
| Top 10 holders %, holder count | GeckoTerminal | A few wallets holding most of the supply can dump the price |
| Risk score and flags | RugCheck | Aggregated contract risks |

All three sources are queried **in parallel** with `asyncio.gather`, so total scan time equals the slowest source, not the sum. If one source fails, the scan still returns everything else and marks missing data as `unknown` — never as safe.

## Example

```
$ python scanner.py JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN
Token:          JUP (Jupiter)
Price:          $0.2603
Liquidity:      $455,881.65
Volume 24h:     $1,504,233.38
Mint Authority: 🟢 disabled
Freeze Auth.:   🟢 disabled
LP locked:      🔴 1.5%
RugCheck risk:  7 (lower is safer)
Scan time:      0.45s
```

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

CLI:

```bash
python scanner.py <token address>
```

Telegram bot:

```bash
cp .env.example .env
python bot.py
```

Set `BOT_TOKEN` in `.env` (get it from [@BotFather](https://t.me/BotFather)).

Mini App API:

```bash
uvicorn api:app --port 8000
```

Telegram requires HTTPS for Mini Apps. Put the public HTTPS URL into `WEBAPP_URL` in `.env` and restart the bot — it will add an **X-Ray** menu button.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

External APIs are mocked — tests run offline in about a second.

### Production (webhook mode)

In production the bot and the Mini App run in **one process**: FastAPI receives Telegram updates on `POST /telegram/webhook` and passes them to aiogram. Webhook mode turns on when `WEBHOOK_SECRET` and `PUBLIC_URL` are set (on Render `PUBLIC_URL` is taken from `RENDER_EXTERNAL_URL` automatically). Telegram signs every webhook request with `X-Telegram-Bot-Api-Secret-Token`; requests without the right secret get `403`.

Deploy on Render: New → Web Service → this repo → Docker, health check path `/health`, env vars `BOT_TOKEN` and `WEBHOOK_SECRET`.

`python bot.py` runs the bot in polling mode for local development and removes the webhook — redeploy (or restart) the service afterwards.

### Docker

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

## Tech stack

- Python 3.14, `asyncio`, `aiohttp`
- `aiogram` 3 — Telegram bot
- FastAPI + Pydantic — Mini App API
- Vanilla JS + Telegram WebApp SDK — Mini App frontend
- pytest + pytest-asyncio, GitHub Actions CI
- Docker / Docker Compose

## Engineering notes

- **Parallel I/O:** three HTTP sources via `asyncio.gather(..., return_exceptions=True)` — one failing source does not break the scan.
- **Timeouts:** 3s for critical sources, 1.5s for optional RugCheck.
- **Caching:** successful RugCheck responses are cached in memory for 5 minutes.
- **Rate limiting:** 5 requests per user per minute (sliding window middleware) and max 10 concurrent scans (semaphore) to protect upstream APIs.
- **Safety:** token names are HTML-escaped before rendering — scam tokens can put markup in their names. The Mini App renders data with `textContent` only.
- **Mini App auth:** every API request carries Telegram `initData`, verified with HMAC-SHA256 using the bot token, and rejected if older than 24h.
- **Money:** prices are `Decimal`, not `float`.

## Roadmap

- [x] CLI scanner
- [x] Telegram bot
- [x] Telegram Mini App
- [ ] Deployment
- [ ] Landing page
- [ ] Web terminal (FastAPI + WebSockets)

## Disclaimer

This tool provides automated on-chain data, not financial advice. A clean result does not guarantee a token is safe.
