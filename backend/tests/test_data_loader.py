from datetime import datetime
import unittest

from app.services.data_loader import get_candles, normalize_timeframe, parse_datetime, realtime_candles, shift_candles_to_now


class DataLoaderTests(unittest.TestCase):
    def test_parse_dataset_datetime_format(self):
        dt = parse_datetime("2026.01.30 23:45")
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.minute, 45)

    def test_timeframe_aliases_normalize_monthly(self):
        self.assertEqual(normalize_timeframe("1month"), "1M")
        self.assertEqual(normalize_timeframe("15m"), "15m")

    def test_get_candles_returns_sorted_limited_rows_from_real_dataset(self):
        rows = get_candles("XAU", "1d", limit=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows, sorted(rows, key=lambda row: row.dt))
        self.assertEqual(rows[-1].close, 4889.48)

    def test_shift_candles_to_now_aligns_last_candle(self):
        rows = get_candles("XAU", "15m", limit=2)
        shifted = shift_candles_to_now(rows, "15m", now=datetime(2026, 5, 15, 10, 47))
        self.assertEqual(shifted[-1].dt.isoformat(timespec="minutes"), "2026-05-15T10:45")
        self.assertEqual(shifted[-1].close, rows[-1].close)

    def test_realtime_candles_can_anchor_last_price(self):
        rows = get_candles("XAU", "15m", limit=2)
        shifted = realtime_candles(rows, "15m", anchor_price=4614, now=datetime(2026, 5, 15, 10, 47))
        self.assertEqual(shifted[-1].dt.isoformat(timespec="minutes"), "2026-05-15T10:45")
        self.assertAlmostEqual(shifted[-1].close, 4614)


if __name__ == "__main__":
    unittest.main()
