from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import DEFAULT_LIMIT
from app.models import CandleOut, PredictionOut, SetupPredictionRequest
from app.services.data_loader import get_candles, normalize_timeframe
from app.services.indicators import indicator_payload
from app.services.prediction import predict_setup
from app.services.zones import detect_zones


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


@app.get("/api/candles", response_model=list[CandleOut])
def candles(
    symbol: str = "XAU",
    timeframe: str = "15m",
    from_value: Annotated[str | None, Query(alias="from")] = None,
    to_value: Annotated[str | None, Query(alias="to")] = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict]:
    try:
        rows = get_candles(symbol, timeframe, from_value, to_value, limit)
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
) -> dict:
    try:
        rows = get_candles(symbol, timeframe, from_value, to_value, limit)
        return indicator_payload(rows) | {"zones": [zone.to_api() for zone in detect_zones(rows)]}
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/predict/setup", response_model=PredictionOut)
def predict(request: SetupPredictionRequest) -> dict:
    try:
        timeframe = normalize_timeframe(request.timeframe)
        rows = get_candles(request.symbol, timeframe, limit=1200)
        zones = detect_zones(rows)
        normalized_request = request.model_copy(update={"timeframe": timeframe})
        return predict_setup(normalized_request, rows, zones)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/replay/stream")
async def replay_stream(
    symbol: str = "XAU",
    timeframe: str = "15m",
    limit: int = 240,
    interval_ms: int = 500,
):
    try:
        rows = get_candles(symbol, timeframe, limit=limit)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_generator():
        for candle in rows:
            yield f"data: {json.dumps(candle.to_api())}\n\n"
            await asyncio.sleep(max(interval_ms, 50) / 1000)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

