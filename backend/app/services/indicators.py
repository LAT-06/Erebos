from __future__ import annotations

from app.services.data_loader import Candle


def ema(values: list[float], period: int) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []

    alpha = 2 / (period + 1)
    output: list[float | None] = []
    current: float | None = None
    for value in values:
        current = value if current is None else (value * alpha) + (current * (1 - alpha))
        output.append(current)
    return output


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(values) < 2:
        return [None for _ in values]

    output: list[float | None] = [None] * len(values)
    gains: list[float] = []
    losses: list[float] = []

    for idx in range(1, len(values)):
        delta = values[idx] - values[idx - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

        if idx < period:
            continue
        if idx == period:
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
        else:
            avg_gain = ((avg_gain * (period - 1)) + gains[-1]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[-1]) / period

        if avg_loss == 0:
            output[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            output[idx] = 100 - (100 / (1 + rs))

    return output


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not candles:
        return []

    true_ranges: list[float] = []
    output: list[float | None] = [None] * len(candles)
    previous_close: float | None = None

    for candle in candles:
        if previous_close is None:
            true_range = candle.high - candle.low
        else:
            true_range = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = candle.close

    current: float | None = None
    for idx, true_range in enumerate(true_ranges):
        if idx < period - 1:
            continue
        if idx == period - 1:
            current = sum(true_ranges[:period]) / period
        else:
            current = ((current or 0) * (period - 1) + true_range) / period
        output[idx] = current

    return output


def indicator_payload(candles: list[Candle]) -> dict:
    closes = [candle.close for candle in candles]
    timestamps = [candle.timestamp for candle in candles]
    ema_lines = {}

    for period in (25, 99, 200):
        ema_lines[f"ema_{period}"] = [
            {"time": time, "value": round(value, 4)}
            for time, value in zip(timestamps, ema(closes, period))
            if value is not None
        ]

    rsi_values = rsi(closes, 14)
    rsi_line = [
        {"time": time, "value": round(value, 2)}
        for time, value in zip(timestamps, rsi_values)
        if value is not None
    ]

    atr_values = atr(candles, 14)
    latest_atr = next((value for value in reversed(atr_values) if value is not None), None)

    return {
        "emas": ema_lines,
        "rsi": rsi_line,
        "latest": {
            "rsi": rsi_line[-1]["value"] if rsi_line else None,
            "atr": round(latest_atr, 4) if latest_atr is not None else None,
        },
    }

