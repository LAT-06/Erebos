from __future__ import annotations

import json
import os
import ssl
import time
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import httpx


GOLD_API_PRICE_URL = "https://api.gold-api.com/price/{symbol}"
OANDA_PRACTICE_API_URL = "https://api-fxpractice.oanda.com"
OANDA_PRACTICE_STREAM_URL = "https://stream-fxpractice.oanda.com"
OANDA_LIVE_API_URL = "https://api-fxtrade.oanda.com"
OANDA_LIVE_STREAM_URL = "https://stream-fxtrade.oanda.com"
QUOTE_CACHE_TTL_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 8.0

_QUOTE_CACHE: dict[str, tuple[float, "LiveQuote"]] = {}


class LivePriceError(RuntimeError):
    """Raised when the live market provider cannot return a usable quote."""


@dataclass(frozen=True)
class LiveQuote:
    symbol: str
    price: float
    currency: str = "USD"
    provider: str = "gold-api.com"
    feed_type: str = "snapshot"
    instrument: str | None = None
    bid: float | None = None
    ask: float | None = None
    updated_at: str | None = None
    fetched_at: datetime | None = None
    raw: dict | None = None

    def to_api(self) -> dict:
        fetched_at = self.fetched_at or datetime.now(timezone.utc)
        return {
            "symbol": self.symbol,
            "price": self.price,
            "currency": self.currency,
            "provider": self.provider,
            "feed_type": self.feed_type,
            "instrument": self.instrument,
            "bid": self.bid,
            "ask": self.ask,
            "updated_at": self.updated_at,
            "fetched_at": fetched_at.isoformat(timespec="seconds"),
        }


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def parse_gold_api_payload(payload: dict) -> LiveQuote:
    symbol = str(payload.get("symbol") or "XAU").upper().strip()
    try:
        price = float(payload["price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LivePriceError("Live provider response did not include a numeric price") from exc

    if price <= 0:
        raise LivePriceError("Live provider returned a non-positive price")

    return LiveQuote(
        symbol=symbol,
        price=price,
        currency=str(payload.get("currency") or "USD").upper().strip(),
        provider="gold-api.com",
        feed_type="snapshot",
        instrument=symbol,
        updated_at=payload.get("updatedAt") or payload.get("updated_at"),
        fetched_at=datetime.now(timezone.utc),
        raw=payload,
    )


def _oanda_env() -> str:
    return os.getenv("OANDA_ENV", "practice").strip().lower()


def _oanda_base_url() -> str:
    return os.getenv("OANDA_API_URL") or (OANDA_LIVE_API_URL if _oanda_env() == "live" else OANDA_PRACTICE_API_URL)


def _oanda_stream_url() -> str:
    return os.getenv("OANDA_STREAM_URL") or (OANDA_LIVE_STREAM_URL if _oanda_env() == "live" else OANDA_PRACTICE_STREAM_URL)


def _oanda_token() -> str | None:
    return os.getenv("OANDA_ACCESS_TOKEN")


def _oanda_account_id() -> str | None:
    return os.getenv("OANDA_ACCOUNT_ID")


def _oanda_instrument(symbol: str) -> str:
    env_key = f"OANDA_INSTRUMENT_{symbol.upper().strip()}"
    return os.getenv(env_key, "XAU_USD")


def oanda_configured() -> bool:
    return bool(_oanda_token() and _oanda_account_id())


def selected_provider() -> str:
    configured = os.getenv("LIVE_PRICE_PROVIDER", "auto").strip().lower()
    if configured == "auto":
        return "oanda" if oanda_configured() else "gold_api"
    return configured


def _best_price_level(levels: list[dict]) -> float | None:
    if not levels:
        return None
    try:
        return float(levels[0]["price"])
    except (KeyError, TypeError, ValueError):
        return None


def parse_oanda_price_payload(payload: dict, symbol: str = "XAU") -> LiveQuote:
    if payload.get("type") == "HEARTBEAT":
        raise LivePriceError("OANDA heartbeat does not include a price")

    bid = _best_price_level(payload.get("bids") or [])
    ask = _best_price_level(payload.get("asks") or [])
    closeout_bid = payload.get("closeoutBid")
    closeout_ask = payload.get("closeoutAsk")
    try:
        if bid is None and closeout_bid is not None:
            bid = float(closeout_bid)
        if ask is None and closeout_ask is not None:
            ask = float(closeout_ask)
    except (TypeError, ValueError) as exc:
        raise LivePriceError("OANDA response included invalid bid/ask values") from exc

    if bid is not None and ask is not None:
        price = (bid + ask) / 2
    elif bid is not None:
        price = bid
    elif ask is not None:
        price = ask
    else:
        raise LivePriceError("OANDA response did not include bid/ask prices")

    if price <= 0:
        raise LivePriceError("OANDA returned a non-positive price")

    normalized_symbol = symbol.upper().strip()
    return LiveQuote(
        symbol=normalized_symbol,
        price=price,
        currency="USD",
        provider="oanda",
        feed_type="streaming",
        instrument=payload.get("instrument") or _oanda_instrument(normalized_symbol),
        bid=bid,
        ask=ask,
        updated_at=payload.get("time"),
        fetched_at=datetime.now(timezone.utc),
        raw=payload,
    )


def clear_quote_cache() -> None:
    _QUOTE_CACHE.clear()


def _get_oanda_quote(symbol: str) -> LiveQuote:
    token = _oanda_token()
    account_id = _oanda_account_id()
    if not token or not account_id:
        raise LivePriceError("OANDA live feed requires OANDA_ACCESS_TOKEN and OANDA_ACCOUNT_ID")

    instrument = _oanda_instrument(symbol)
    url = f"{_oanda_base_url()}/v3/accounts/{account_id}/pricing?instruments={quote(instrument)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Erebos-XAU-Trading-Platform/0.1",
        },
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise LivePriceError(f"OANDA quote HTTP error {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LivePriceError(f"OANDA quote is unreachable: {exc}") from exc

    prices = payload.get("prices") or []
    if not prices:
        raise LivePriceError("OANDA quote response did not include prices")
    return parse_oanda_price_payload(prices[0], symbol)


def _get_gold_api_quote(symbol: str) -> LiveQuote:
    url = GOLD_API_PRICE_URL.format(symbol=symbol)
    request = Request(url, headers={"User-Agent": "Erebos-XAU-Trading-Platform/0.1"})
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS, context=_ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise LivePriceError(f"Live provider HTTP error {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LivePriceError(f"Live provider is unreachable: {exc}") from exc

    return parse_gold_api_payload(payload)


def get_live_quote(symbol: str = "XAU", *, force_refresh: bool = False) -> LiveQuote:
    normalized = symbol.upper().strip()
    if normalized != "XAU":
        raise LivePriceError(f"Unsupported live symbol: {normalized}")

    provider = selected_provider()
    now = time.monotonic()
    cache_key = f"{provider}:{normalized}"
    cached = _QUOTE_CACHE.get(cache_key)
    if cached and not force_refresh and now - cached[0] <= QUOTE_CACHE_TTL_SECONDS:
        return cached[1]

    if provider == "oanda":
        quote = _get_oanda_quote(normalized)
    elif provider in {"gold", "gold_api", "gold-api.com"}:
        quote = _get_gold_api_quote(normalized)
    else:
        raise LivePriceError(f"Unsupported LIVE_PRICE_PROVIDER: {provider}")

    _QUOTE_CACHE[cache_key] = (now, quote)
    return quote


async def stream_oanda_quotes(symbol: str = "XAU") -> AsyncIterator[LiveQuote]:
    token = _oanda_token()
    account_id = _oanda_account_id()
    if not token or not account_id:
        raise LivePriceError("OANDA live stream requires OANDA_ACCESS_TOKEN and OANDA_ACCOUNT_ID")

    normalized = symbol.upper().strip()
    instrument = _oanda_instrument(normalized)
    url = f"{_oanda_stream_url()}/v3/accounts/{account_id}/pricing/stream?instruments={quote(instrument)}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "Erebos-XAU-Trading-Platform/0.1"}
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code >= 400:
                raise LivePriceError(f"OANDA stream HTTP error {response.status_code}")
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") == "HEARTBEAT":
                    continue
                yield parse_oanda_price_payload(payload, normalized)


async def stream_live_quotes(symbol: str = "XAU", poll_interval_seconds: float = 1.0) -> AsyncIterator[LiveQuote]:
    provider = selected_provider()
    if provider == "oanda":
        async for quote in stream_oanda_quotes(symbol):
            yield quote
        return

    while True:
        yield get_live_quote(symbol, force_refresh=True)
        await asyncio.sleep(max(poll_interval_seconds, 0.25))
