from __future__ import annotations

import csv
from dataclasses import dataclass
from dataclasses import replace
from collections import deque
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from app.config import DATASET_ROOT, DEFAULT_LIMIT, MAX_LIMIT, TIMEFRAME_ALIASES, TIMEFRAME_FILES


DATE_FORMAT = "%Y.%m.%d %H:%M"
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
    "1M": 2592000,
}


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    dt: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def timestamp(self) -> int:
        return int(self.dt.replace(tzinfo=timezone.utc).timestamp())

    def to_api(self) -> dict:
        return {
            "time": self.timestamp,
            "datetime": self.dt.isoformat(timespec="minutes"),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


def normalize_timeframe(timeframe: str) -> str:
    raw = timeframe.strip()
    key = raw.lower()
    return TIMEFRAME_ALIASES.get(key, raw)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    try:
        return datetime.strptime(raw, DATE_FORMAT)
    except ValueError:
        pass

    iso_value = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def dataset_path(symbol: str, timeframe: str) -> Path:
    symbol = symbol.upper().strip()
    timeframe = normalize_timeframe(timeframe)
    if symbol != "XAU":
        raise ValueError(f"Unsupported symbol: {symbol}")
    if timeframe not in TIMEFRAME_FILES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return DATASET_ROOT / "xau" / TIMEFRAME_FILES[timeframe]


def _row_to_candle(symbol: str, timeframe: str, row: dict[str, str]) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        dt=parse_datetime(row["Date"]) or datetime.min,
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=float(row["Volume"]),
    )


@lru_cache(maxsize=64)
def load_recent_candles(symbol: str, timeframe: str, limit: int) -> tuple[Candle, ...]:
    symbol = symbol.upper().strip()
    timeframe = normalize_timeframe(timeframe)
    path = dataset_path(symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")

    rows: deque[dict[str, str]] = deque(maxlen=max(limit, 1))
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")
        for row in reader:
            rows.append(row)

    candles = [_row_to_candle(symbol, timeframe, row) for row in rows]
    candles.sort(key=lambda candle: candle.dt)
    return tuple(candles)


@lru_cache(maxsize=16)
def load_candles(symbol: str, timeframe: str) -> tuple[Candle, ...]:
    symbol = symbol.upper().strip()
    timeframe = normalize_timeframe(timeframe)
    path = dataset_path(symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(f"Missing dataset file: {path}")

    candles: list[Candle] = []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name} is missing columns: {sorted(missing)}")

        for row in reader:
            candles.append(_row_to_candle(symbol, timeframe, row))

    candles.sort(key=lambda candle: candle.dt)
    deduped: list[Candle] = []
    seen: set[datetime] = set()
    for candle in candles:
        if candle.dt in seen:
            deduped[-1] = candle
            continue
        seen.add(candle.dt)
        deduped.append(candle)

    return tuple(deduped)


def filter_candles(
    candles: Iterable[Candle],
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int | None = DEFAULT_LIMIT,
) -> list[Candle]:
    bounded_limit = min(max(limit or DEFAULT_LIMIT, 1), MAX_LIMIT)
    filtered = [
        candle
        for candle in candles
        if (from_dt is None or candle.dt >= from_dt) and (to_dt is None or candle.dt <= to_dt)
    ]
    if len(filtered) > bounded_limit:
        return filtered[-bounded_limit:]
    return filtered


def get_candles(
    symbol: str,
    timeframe: str,
    from_value: str | None = None,
    to_value: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
) -> list[Candle]:
    if from_value is None and to_value is None and limit is not None:
        candles = load_recent_candles(symbol, timeframe, min(max(limit, 1), MAX_LIMIT))
    else:
        candles = load_candles(symbol, timeframe)
    return filter_candles(candles, parse_datetime(from_value), parse_datetime(to_value), limit)


def align_to_timeframe(dt: datetime, timeframe: str) -> datetime:
    timeframe = normalize_timeframe(timeframe)
    seconds = TIMEFRAME_SECONDS.get(timeframe, 900)
    timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())
    aligned = timestamp - (timestamp % seconds)
    return datetime.fromtimestamp(aligned, tz=timezone.utc).replace(tzinfo=None)


def shift_candles_to_now(candles: list[Candle], timeframe: str, now: datetime | None = None) -> list[Candle]:
    if not candles:
        return []
    aligned_now = align_to_timeframe(now or datetime.now(), timeframe)
    delta = aligned_now - candles[-1].dt
    return [replace(candle, dt=candle.dt + delta) for candle in candles]


def scale_candles_to_anchor(candles: list[Candle], anchor_price: float | None) -> list[Candle]:
    if not candles or anchor_price is None or anchor_price <= 0:
        return candles
    last_close = candles[-1].close
    if last_close <= 0:
        return candles
    factor = anchor_price / last_close
    return [
        replace(
            candle,
            open=candle.open * factor,
            high=candle.high * factor,
            low=candle.low * factor,
            close=candle.close * factor,
        )
        for candle in candles
    ]


def realtime_candles(
    candles: list[Candle],
    timeframe: str,
    anchor_price: float | None = None,
    now: datetime | None = None,
) -> list[Candle]:
    return scale_candles_to_anchor(shift_candles_to_now(candles, timeframe, now), anchor_price)
