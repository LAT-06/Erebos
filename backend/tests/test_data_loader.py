import unittest

from app.services.data_loader import get_candles, normalize_timeframe, parse_datetime


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


if __name__ == "__main__":
    unittest.main()
