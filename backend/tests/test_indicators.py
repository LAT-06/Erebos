from datetime import datetime, timedelta
import unittest

from app.services.data_loader import Candle
from app.services.indicators import atr, ema, rsi


def make_candle(index: int, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        symbol="XAU",
        timeframe="15m",
        dt=datetime(2024, 1, 1) + timedelta(minutes=15 * index),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


class IndicatorTests(unittest.TestCase):
    def test_ema_uses_standard_smoothing_factor(self):
        values = [10.0, 12.0, 14.0]
        result = ema(values, 2)
        self.assertEqual(result[0], 10.0)
        self.assertAlmostEqual(result[1], 11.333333333333334)
        self.assertAlmostEqual(result[2], 13.111111111111112)

    def test_rsi_returns_high_value_for_one_way_rally(self):
        values = [float(value) for value in range(1, 25)]
        result = rsi(values, 14)
        self.assertEqual(result[-1], 100.0)

    def test_atr_uses_true_range_with_previous_close(self):
        candles = [
            make_candle(0, 10, 12, 9, 11),
            make_candle(1, 11, 15, 10, 14),
            make_candle(2, 14, 16, 13, 15),
        ]
        result = atr(candles, 2)
        self.assertIsNone(result[0])
        self.assertEqual(result[1], 4.0)
        self.assertEqual(result[2], 3.5)


if __name__ == "__main__":
    unittest.main()
