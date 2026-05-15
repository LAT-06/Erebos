from __future__ import annotations

import math
from datetime import datetime
from functools import lru_cache
from typing import Any

from app.config import MODEL_PATH
from app.models import SetupPredictionRequest
from app.services.data_loader import Candle, load_candles
from app.services.indicators import atr, ema, indicator_payload, rsi
from app.services.zones import Zone, detect_zones, nearest_zones


TIMEFRAME_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
    "1M": 43200,
}

CONTEXT_TIMEFRAMES = ("5m", "4h", "1d", "1w")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def risk_reward(side: str, entry: float, stop_loss: float, take_profit: float) -> float:
    side = side.lower()
    if side == "long":
        risk = entry - stop_loss
        reward = take_profit - entry
    elif side == "short":
        risk = stop_loss - entry
        reward = entry - take_profit
    else:
        raise ValueError(f"Unsupported side: {side}")
    if risk <= 0 or reward <= 0:
        raise ValueError("Invalid setup geometry for side, entry, stop_loss, and take_profit")
    return reward / risk


@lru_cache(maxsize=1)
def load_model_bundle() -> dict[str, Any] | None:
    if not MODEL_PATH.exists():
        return None
    try:
        import joblib
    except ImportError:
        return None
    return joblib.load(MODEL_PATH)


def _model_probability(request: SetupPredictionRequest, candles: list[Candle], zones: list[Zone]) -> float | None:
    bundle = load_model_bundle()
    if not bundle:
        return None

    model = bundle.get("model")
    feature_columns = bundle.get("feature_columns", [])
    if model is None or not feature_columns:
        return None

    feature_map = build_runtime_feature_map(request, candles, zones)
    row_values = [feature_map.get(column, 0.0) or 0.0 for column in feature_columns]

    try:
        import pandas as pd

        row = pd.DataFrame([row_values], columns=feature_columns)
    except ImportError:
        row = [row_values]

    if hasattr(model, "predict_proba"):
        return float(model.predict_proba(row)[0][1])
    if hasattr(model, "predict"):
        return float(model.predict(row)[0])
    return None


def _last_index_at_or_before(candles: tuple[Candle, ...] | list[Candle], dt: datetime) -> int | None:
    low = 0
    high = len(candles) - 1
    answer: int | None = None
    while low <= high:
        mid = (low + high) // 2
        if candles[mid].dt <= dt:
            answer = mid
            low = mid + 1
        else:
            high = mid - 1
    return answer


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _latest_feature_map(candles: list[Candle], zones: list[Zone], prefix: str) -> dict[str, float | int | None]:
    latest = candles[-1]
    previous = candles[-2] if len(candles) >= 2 else None
    closes = [candle.close for candle in candles]
    atr_values = atr(candles, 14)
    latest_atr = next((value for value in reversed(atr_values) if value is not None), None)
    safe_atr = latest_atr or max(latest.high - latest.low, latest.close * 0.001)
    rsi_values = rsi(closes, 14)
    ema_values = {period: ema(closes, period) for period in (25, 99, 200)}
    zone_context = nearest_zones(latest.close, zones)
    support = zone_context.get("nearest_support")
    resistance = zone_context.get("nearest_resistance")

    log_returns: list[float] = []
    for idx in range(max(1, len(closes) - 20), len(closes)):
        if closes[idx - 1] > 0 and closes[idx] > 0:
            log_returns.append(math.log(closes[idx]) - math.log(closes[idx - 1]))

    result: dict[str, float | int | None] = {
        "open": latest.open,
        "high": latest.high,
        "low": latest.low,
        "close": latest.close,
        "volume": latest.volume,
        "return_1": ((latest.close - previous.close) / previous.close) if previous and previous.close else None,
        "log_return_1": (math.log(latest.close) - math.log(previous.close)) if previous and previous.close > 0 else None,
        "volatility_20": _stddev(log_returns),
        "atr_14": latest_atr,
        "rsi_14": rsi_values[-1],
        "body_atr": abs(latest.close - latest.open) / safe_atr,
        "upper_wick_atr": (latest.high - max(latest.open, latest.close)) / safe_atr,
        "lower_wick_atr": (min(latest.open, latest.close) - latest.low) / safe_atr,
        "dist_to_resistance_atr": ((resistance["price"] - latest.close) / safe_atr) if resistance else None,
        "dist_to_support_atr": ((latest.close - support["price"]) / safe_atr) if support else None,
        "near_liquidity_high": 0,
        "near_liquidity_low": 0,
        "hour": latest.dt.hour,
        "dayofweek": latest.dt.weekday(),
        "session_asia": 1 if 0 <= latest.dt.hour <= 7 else 0,
        "session_london": 1 if 7 <= latest.dt.hour <= 15 else 0,
        "session_new_york": 1 if 13 <= latest.dt.hour <= 21 else 0,
    }

    for period, values in ema_values.items():
        current = values[-1]
        previous_ema = values[-2] if len(values) >= 2 else None
        result[f"ema_{period}"] = current
        result[f"ema_{period}_slope"] = (current - previous_ema) if current is not None and previous_ema is not None else None
        result[f"close_to_ema_{period}_atr"] = ((latest.close - current) / safe_atr) if current is not None else None

    liquidity_high = zone_context.get("nearest_resistance")
    liquidity_low = zone_context.get("nearest_support")
    result["near_liquidity_high"] = 1 if liquidity_high and liquidity_high["distance"] <= safe_atr * 1.5 else 0
    result["near_liquidity_low"] = 1 if liquidity_low and liquidity_low["distance"] <= safe_atr * 1.5 else 0

    return {f"{prefix}_{key}": value for key, value in result.items()}


def build_runtime_feature_map(request: SetupPredictionRequest, candles: list[Candle], zones: list[Zone]) -> dict[str, float | int | None]:
    rr = risk_reward(request.side, request.entry, request.stop_loss, request.take_profit)
    base_atr = indicator_payload(candles)["latest"]["atr"] or max(candles[-1].high - candles[-1].low, candles[-1].close * 0.001)
    timeframe_minutes = TIMEFRAME_MINUTES.get(request.timeframe, 15)
    latest_dt = candles[-1].dt

    feature_map: dict[str, float | int | None] = {
        "entry": request.entry,
        "stop_loss": request.stop_loss,
        "take_profit": request.take_profit,
        "risk_reward": rr,
        "sl_atr": abs(request.entry - request.stop_loss) / base_atr,
        "horizon_bars": max(1, round(request.horizon_minutes / timeframe_minutes)),
        "horizon_minutes": request.horizon_minutes,
        "side_long": 1 if request.side == "long" else 0,
    }
    feature_map.update(_latest_feature_map(candles, zones, "base"))

    for timeframe in CONTEXT_TIMEFRAMES:
        if timeframe == request.timeframe:
            continue
        try:
            all_context = load_candles(request.symbol, timeframe)
        except (FileNotFoundError, ValueError):
            continue
        idx = _last_index_at_or_before(all_context, latest_dt)
        if idx is None:
            continue
        window = list(all_context[max(0, idx - 1200) : idx + 1])
        context_zones = detect_zones(window)
        feature_map.update(_latest_feature_map(window, context_zones, timeframe))

    # Compatibility aliases for early, narrower model experiments.
    latest = candles[-1]
    feature_map.setdefault("close", latest.close)
    feature_map.setdefault("rsi_14", indicator_payload(candles)["latest"]["rsi"])
    for period in (25, 99, 200):
        feature_map.setdefault(f"ema_{period}", feature_map.get(f"base_ema_{period}"))

    return feature_map


def _heuristic_probability(request: SetupPredictionRequest, candles: list[Candle], zones: list[Zone]) -> tuple[float, dict]:
    closes = [candle.close for candle in candles]
    latest = candles[-1]
    payload = indicator_payload(candles)
    latest_rsi = payload["latest"]["rsi"]
    latest_atr = payload["latest"]["atr"] or max(latest.high - latest.low, latest.close * 0.001)
    ema25 = ema(closes, 25)[-1] or latest.close
    ema99 = ema(closes, 99)[-1] or latest.close
    ema200 = ema(closes, 200)[-1] or latest.close
    rr = risk_reward(request.side, request.entry, request.stop_loss, request.take_profit)
    zone_context = nearest_zones(request.entry, zones)

    trend_score = 0.0
    if request.side == "long":
        trend_score += 0.08 if ema25 > ema99 > ema200 else -0.06
        trend_score += 0.04 if latest.close > ema25 else -0.03
        trend_score += 0.03 if latest_rsi is not None and 42 <= latest_rsi <= 68 else -0.03
    else:
        trend_score += 0.08 if ema25 < ema99 < ema200 else -0.06
        trend_score += 0.04 if latest.close < ema25 else -0.03
        trend_score += 0.03 if latest_rsi is not None and 32 <= latest_rsi <= 58 else -0.03

    rr_score = clamp(math.log(max(rr, 0.2)) * 0.07, -0.08, 0.12)
    distance_to_entry = abs(request.entry - latest.close)
    entry_score = clamp(0.05 - (distance_to_entry / max(latest_atr, 0.0001)) * 0.025, -0.08, 0.05)

    zone_score = 0.0
    nearest_support = zone_context.get("nearest_support")
    nearest_resistance = zone_context.get("nearest_resistance")
    if request.side == "long":
        if nearest_support and nearest_support["distance"] <= latest_atr * 1.5:
            zone_score += 0.05
        if nearest_resistance and nearest_resistance["distance"] <= latest_atr * 1.2:
            zone_score -= 0.05
    else:
        if nearest_resistance and nearest_resistance["distance"] <= latest_atr * 1.5:
            zone_score += 0.05
        if nearest_support and nearest_support["distance"] <= latest_atr * 1.2:
            zone_score -= 0.05

    horizon_score = clamp((request.horizon_minutes / 240) * 0.015, 0.0, 0.04)
    probability = clamp(0.50 + trend_score + rr_score + entry_score + zone_score + horizon_score, 0.05, 0.95)

    context = zone_context | {
        "latest_close": latest.close,
        "latest_rsi": latest_rsi,
        "latest_atr": latest_atr,
        "ema_25": round(ema25, 4),
        "ema_99": round(ema99, 4),
        "ema_200": round(ema200, 4),
        "notes": [
            "Heuristic fallback is active until a trained model artifact is exported.",
            "Same-candle TP/SL ambiguity is treated conservatively in training labels.",
        ],
    }
    return probability, context


def verdict_from_probability(probability: float) -> str:
    if probability >= 0.58:
        return "valid"
    if probability >= 0.45:
        return "watch"
    return "avoid"


def predict_setup(request: SetupPredictionRequest, candles: list[Candle], zones: list[Zone]) -> dict:
    if len(candles) < 30:
        raise ValueError("Not enough candles to compute prediction context")

    rr = risk_reward(request.side, request.entry, request.stop_loss, request.take_profit)
    model_probability = _model_probability(request, candles, zones)
    if model_probability is None:
        probability, context = _heuristic_probability(request, candles, zones)
        source = "heuristic"
    else:
        probability = clamp(model_probability, 0.0, 1.0)
        context = nearest_zones(request.entry, zones)
        source = "model"

    confidence = clamp(abs(probability - 0.5) * 2, 0.0, 1.0)
    return {
        "symbol": request.symbol,
        "timeframe": request.timeframe,
        "side": request.side,
        "win_probability": round(probability, 4),
        "calibrated_confidence": round(confidence, 4),
        "risk_reward": round(rr, 3),
        "verdict": verdict_from_probability(probability),
        "context": context,
        "model_source": source,
    }
