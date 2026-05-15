from datetime import datetime, timedelta
import unittest

from app.services.data_loader import Candle
from app.services.labels import tp_before_sl


def candle(index: int, high: float, low: float) -> Candle:
    return Candle(
        symbol="XAU",
        timeframe="15m",
        dt=datetime(2024, 1, 1) + timedelta(minutes=15 * index),
        open=100,
        high=high,
        low=low,
        close=100,
        volume=1,
    )


class LabelTests(unittest.TestCase):
    def test_long_tp_before_sl_wins(self):
        self.assertEqual(tp_before_sl([candle(1, high=105, low=99)], "long", stop_loss=98, take_profit=104), 1)

    def test_short_tp_before_sl_wins(self):
        self.assertEqual(tp_before_sl([candle(1, high=101, low=95)], "short", stop_loss=103, take_profit=96), 1)

    def test_same_candle_ambiguity_is_conservative_loss(self):
        self.assertEqual(tp_before_sl([candle(1, high=105, low=95)], "long", stop_loss=96, take_profit=104), 0)

    def test_missing_future_window_returns_none(self):
        self.assertIsNone(tp_before_sl([], "long", stop_loss=98, take_profit=104))


if __name__ == "__main__":
    unittest.main()

