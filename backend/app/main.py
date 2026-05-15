from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import DEFAULT_LIMIT
from app.models import CandleOut, PredictionOut, SetupPredictionRequest, SetupSuggestionOut
from app.services.data_loader import (
    TIMEFRAME_SECONDS,
    Candle,
    align_to_timeframe,
    get_candles,
    normalize_timeframe,
    realtime_candles,
)
from app.services.indicators import indicator_payload
from app.services.live_price import LivePriceError, LiveQuote, get_live_quote, oanda_configured, selected_provider, stream_live_quotes
from app.services.prediction import clear_model_cache, model_status, predict_setup, suggest_limit_setups
from app.services.zones import detect_zones


ZONE_TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")


app = FastAPI(title="XAU Trading Platform API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/model/status")
def get_model_status() -> dict:
    return model_status()


@app.post("/api/model/reload")
def reload_model() -> dict:
    clear_model_cache()
    return model_status()


def _live_quote_or_http(symbol: str) -> LiveQuote:
    try:
        return get_live_quote(symbol)
    except LivePriceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resolve_live_price(symbol: str, anchor_price: float | None = None) -> tuple[float, LiveQuote | None]:
    if anchor_price is not None and anchor_price > 0:
        return anchor_price, None
    quote = _live_quote_or_http(symbol)
    return quote.price, quote


def _realtime_rows(symbol: str, timeframe: str, rows: list[Candle], anchor_price: float | None = None) -> tuple[list[Candle], LiveQuote | None]:
    price, quote = _resolve_live_price(symbol, anchor_price)
    return realtime_candles(rows, timeframe, price), quote


def _source_meta(realtime: bool, quote: LiveQuote | None, anchor_price: float | None = None) -> dict:
    if not realtime:
        return {"source": "csv_historical"}
    if quote is not None:
        return {"source": "live_market_quote", "live_quote": quote.to_api()}
    return {"source": "manual_anchor", "anchor_price": anchor_price}


@app.get("/api/live/quote")
def live_quote(symbol: str = "XAU") -> dict:
    return _live_quote_or_http(symbol).to_api()


@app.get("/api/live/status")
def live_status() -> dict:
    provider = selected_provider()
    return {
        "provider": provider,
        "feed_type": "streaming" if provider == "oanda" and oanda_configured() else "snapshot",
        "oanda_configured": oanda_configured(),
        "fallback": "gold-api.com" if provider != "oanda" else None,
    }


@app.get("/api/candles", response_model=list[CandleOut])
def candles(
    symbol: str = "XAU",
    timeframe: str = "15m",
    from_value: Annotated[str | None, Query(alias="from")] = None,
    to_value: Annotated[str | None, Query(alias="to")] = None,
    limit: int = DEFAULT_LIMIT,
    realtime: bool = False,
    anchor_price: float | None = None,
) -> list[dict]:
    try:
        rows = get_candles(symbol, timeframe, from_value, to_value, limit)
        if realtime:
            rows, _ = _realtime_rows(symbol, timeframe, rows, anchor_price)
        return [row.to_api() for row in rows]
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/indicators")
def indicators(
    symbol: str = "XAU",
    timeframe: str = "15m",
    from_value: Annotated[str | None, Query(alias="from")] = None,
    to_value: Annotated[str | None, Query(alias="to")] = None,
    limit: int = DEFAULT_LIMIT,
    realtime: bool = False,
    anchor_price: float | None = None,
) -> dict:
    try:
        rows = get_candles(symbol, timeframe, from_value, to_value, limit)
        quote = None
        if realtime:
            rows, quote = _realtime_rows(symbol, timeframe, rows, anchor_price)
        return indicator_payload(rows) | {
            "zones": [zone.to_api() for zone in detect_zones(rows, timeframe=timeframe)],
        } | _source_meta(realtime, quote, anchor_price)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/predict/setup", response_model=PredictionOut)
def predict(request: SetupPredictionRequest) -> dict:
    try:
        timeframe = normalize_timeframe(request.timeframe)
        rows = get_candles(request.symbol, timeframe, limit=1200)
        quote = None
        live_price = request.anchor_price
        if request.realtime:
            rows, quote = _realtime_rows(request.symbol, timeframe, rows, request.anchor_price)
            live_price = rows[-1].close if rows else request.anchor_price
        zones = detect_zones(rows, timeframe=timeframe)
        normalized_request = request.model_copy(update={"timeframe": timeframe, "anchor_price": live_price})
        result = predict_setup(normalized_request, rows, zones)
        if quote is not None:
            result["context"] = result.get("context", {}) | {"live_quote": quote.to_api()}
        return result
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/setups/suggest", response_model=list[SetupSuggestionOut])
def suggest_setups(
    symbol: str = "XAU",
    timeframe: str = "15m",
    side: str | None = None,
    horizon_minutes: int | None = None,
    max_suggestions: int = 6,
    realtime: bool = False,
    anchor_price: float | None = None,
) -> list[dict]:
    try:
        timeframe = normalize_timeframe(timeframe)
        rows = get_candles(symbol, timeframe, limit=1200)
        live_price = anchor_price
        if realtime:
            rows, _ = _realtime_rows(symbol, timeframe, rows, anchor_price)
            live_price = rows[-1].close if rows else anchor_price
        zones = detect_zones(rows, timeframe=timeframe)
        return suggest_limit_setups(
            symbol=symbol.upper().strip(),
            timeframe=timeframe,
            side=side,
            horizon_minutes=horizon_minutes,
            candles=rows,
            zones=zones,
            max_suggestions=max(1, min(max_suggestions, 12)),
            realtime=realtime,
            anchor_price=live_price,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/zones")
def zones(
    symbol: str = "XAU",
    timeframes: str = ",".join(ZONE_TIMEFRAMES),
    limit: int = 900,
    realtime: bool = False,
    anchor_price: float | None = None,
) -> dict:
    try:
        requested = [normalize_timeframe(item) for item in timeframes.split(",") if item.strip()]
        if not requested:
            requested = list(ZONE_TIMEFRAMES)

        output = []
        quote = None
        live_price = anchor_price
        if realtime:
            live_price, quote = _resolve_live_price(symbol, anchor_price)
        for timeframe in requested:
            rows = get_candles(symbol, timeframe, limit=limit)
            if realtime:
                rows = realtime_candles(rows, timeframe, live_price)
            output.extend(zone.to_api() for zone in detect_zones(rows, timeframe=timeframe))

        output.sort(key=lambda item: (item["strength"], item["last_time"]), reverse=True)
        return {
            "symbol": symbol.upper().strip(),
            "timeframes": requested,
            "liquidity_note": "volume/notional are estimates from CSV candle volume, not live order-book liquidity",
            "zones": output,
        } | _source_meta(realtime, quote, anchor_price)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/replay/stream")
async def replay_stream(
    symbol: str = "XAU",
    timeframe: str = "15m",
    limit: int = 240,
    interval_ms: int = 500,
    realtime: bool = False,
    anchor_price: float | None = None,
):
    try:
        rows = get_candles(symbol, timeframe, limit=limit)
        if realtime:
            rows, _ = _realtime_rows(symbol, timeframe, rows, anchor_price)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_generator():
        for candle in rows:
            yield f"data: {json.dumps(candle.to_api())}\n\n"
            await asyncio.sleep(max(interval_ms, 50) / 1000)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/live/stream")
async def live_stream(
    symbol: str = "XAU",
    timeframe: str = "15m",
    interval_ms: int = 1000,
    anchor_price: float | None = None,
):
    try:
        timeframe = normalize_timeframe(timeframe)
        seed_price, seed_quote = _resolve_live_price(symbol, anchor_price)
        rows = realtime_candles(get_candles(symbol, timeframe, limit=60), timeframe, seed_price)
        if not rows:
            raise ValueError("No candles available")
        base = rows[-1]
        timeframe_seconds = TIMEFRAME_SECONDS.get(timeframe, 900)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_generator():
        candle_open = base.open
        high = base.high
        low = base.low
        last_close = seed_price
        current_bucket_dt = base.dt
        last_quote = seed_quote
        async for quote in stream_live_quotes(symbol, max(interval_ms, 250) / 1000):
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            bucket_dt = align_to_timeframe(now, timeframe)
            if bucket_dt != current_bucket_dt:
                candle_open = last_close
                high = last_close
                low = last_close
                current_bucket_dt = bucket_dt

            if anchor_price is not None:
                quote = last_quote
                close = anchor_price
            else:
                last_quote = quote
                close = quote.price

            high = max(high, close, candle_open)
            low = min(low, close, candle_open)
            last_close = close
            candle = Candle(
                symbol=symbol.upper().strip(),
                timeframe=timeframe,
                dt=current_bucket_dt,
                open=candle_open,
                high=high,
                low=low,
                close=close,
                volume=base.volume,
            )
            payload = candle.to_api() | {
                "source": "live_market_quote" if quote is not None else "manual_anchor",
                "market_price": close,
                "provider": quote.provider if quote is not None else None,
                "feed_type": quote.feed_type if quote is not None else "manual_anchor",
                "quote": quote.to_api() if quote is not None else None,
                "timeframe_seconds": timeframe_seconds,
            }
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
