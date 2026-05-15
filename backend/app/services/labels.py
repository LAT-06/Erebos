from __future__ import annotations

from app.services.data_loader import Candle


def tp_before_sl(
    future_candles: list[Candle],
    side: str,
    stop_loss: float,
    take_profit: float,
) -> int | None:
    if not future_candles:
        return None

    side = side.lower()
    for candle in future_candles:
        if side == "long":
            hit_tp = candle.high >= take_profit
            hit_sl = candle.low <= stop_loss
        elif side == "short":
            hit_tp = candle.low <= take_profit
            hit_sl = candle.high >= stop_loss
        else:
            raise ValueError(f"Unsupported side: {side}")

        if hit_tp and hit_sl:
            return 0
        if hit_tp:
            return 1
        if hit_sl:
            return 0

    return 0

