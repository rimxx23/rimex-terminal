# Rimex Terminal

[![tests](https://github.com/rimxx23/rimex-terminal/actions/workflows/tests.yml/badge.svg)](https://github.com/rimxx23/rimex-terminal/actions/workflows/tests.yml)

Rimex Terminal is a website for scanning Solana tokens and practicing SOL/USDT trading with virtual balances.

## Quick start

```bash
docker compose up -d --build
```

Open [Rimex Terminal](http://localhost:8001/) and create an account. Sign in to
use the token scanner and demo trading. Each account starts with 10,000 virtual
USDT and 5 virtual SOL. When you register in a browser with an existing guest
wallet, Rimex carries over its balance and trading history.

The SOL/USDT terminal shows public Binance candles at 1m, 5m and 15m, with
your fills and active orders overlaid. Limit orders can rest in the book and
be cancelled. Market orders execute against available liquidity within 1%
of the live quote and cancel any remainder. Public Binance quotes drive
simulated liquidity. SQLite stores accounts, balances, orders and fills in the Docker
volume. Rimex pauses new orders when the quote expires.

Docker Compose reads optional settings from `.env`. Set `RIMEX_PORT` to change
the host port, `SOLANA_RPC_URL` to use another Solana RPC provider, or
`FORWARDED_ALLOW_IPS` to trust a designated reverse proxy.

To run directly with Python:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn rimex.presentation.api.app:app --port 8001
```

## Architecture

The website uses HTML, CSS and JavaScript in `webapp/`. FastAPI exposes the
website and its API. Inside `rimex/`, services coordinate scanning and trading,
clients fetch external data, and domain modules define risk and order rules.

## What it checks

| Check | Source | Why it matters |
|---|---|---|
| Price, liquidity, 24h volume | DexScreener, fallback GeckoTerminal | Market data; GeckoTerminal is used when DexScreener is rate-limited or has no pairs |
| Mint Authority | Solana RPC | If enabled, the owner can print unlimited tokens |
| Freeze Authority | Solana RPC | If enabled, the owner can freeze your tokens |
| Honeypot signs | Solana RPC (Token-2022 extensions), GeckoTerminal | Transfer hook, permanent delegate, freeze authority or a high transfer fee can stop you from selling |
| LP locked % | RugCheck | Unlocked liquidity can be pulled (rug pull) |
| Top 10 holders %, holder count | GeckoTerminal | A few wallets holding most of the supply can dump the price |
| Developer holding % | GeckoTerminal | A large developer bag can be dumped on buyers (🟡 from 5%, 🔴 from 20%) |
| Pool age | DexScreener | Fresh pools are the riskiest (🔴 under 1 day, 🟡 under 7 days) |
| Known tokens | Built-in list (USDC, USDT, PYUSD) | Regulated stablecoins keep freeze powers by design — shown as 🟡 with the issuer name instead of 🔴 |
| Risk score and flags | RugCheck | Aggregated contract risks |

All sources are queried **in parallel** with `asyncio.gather`, so total scan time equals the slowest source, not the sum. If one source fails, the scan still returns everything else and marks missing data as `unknown` — never as safe.

## Example

```
$ python -m rimex JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN
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

## Tests

```bash
pip install -r requirements-dev.txt
pytest
node --test "tests/js/*.test.mjs"
```

## Tech stack

- Python 3.14, `asyncio`, `aiohttp`
- FastAPI + Pydantic — web API
- Vanilla JavaScript and SQLite
- pytest + pytest-asyncio, GitHub Actions CI
- Docker / Docker Compose

## Engineering notes

- **Website:** overall verdict on each scan, with the last 10 scans stored in the browser.

- **Parallel I/O:** three HTTP sources via `asyncio.gather(..., return_exceptions=True)` — one failing source does not break the scan.
- **Timeouts:** 3s for critical sources, 1.5s for optional RugCheck.
- **Caching:** successful RugCheck responses are cached in memory for 5 minutes.
- **Rate limiting:** 5 scans per IP per minute and max 10 concurrent scans (semaphore) to protect upstream APIs.
- **Safety:** token names are HTML-escaped before rendering — scam tokens can put markup in their names. The website renders data with `textContent` only.
- **Web auth:** session cookies are checked by the server and revoked on sign-out.
- **Money:** prices are `Decimal`, not `float`.

## Roadmap

- [x] CLI scanner
- [x] Web scanner and SOL/USDT demo trading
- [ ] Deployment
- [ ] Landing page
- [ ] Web terminal (FastAPI + WebSockets)

## Disclaimer

This tool provides automated on-chain data, not financial advice. A clean result does not guarantee a token is safe.
