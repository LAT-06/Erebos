import unittest

from app.services.live_price import LivePriceError, parse_gold_api_payload, parse_oanda_price_payload


class LivePriceTests(unittest.TestCase):
    def test_parse_gold_api_payload_returns_quote(self):
        quote = parse_gold_api_payload(
            {
                "currency": "USD",
                "name": "Gold",
                "price": 4610.799805,
                "symbol": "XAU",
                "updatedAt": "2026-05-15T04:54:00Z",
            }
        )
        self.assertEqual(quote.symbol, "XAU")
        self.assertEqual(quote.currency, "USD")
        self.assertAlmostEqual(quote.price, 4610.799805)
        self.assertEqual(quote.feed_type, "snapshot")
        self.assertEqual(quote.updated_at, "2026-05-15T04:54:00Z")

    def test_parse_gold_api_payload_rejects_missing_price(self):
        with self.assertRaises(LivePriceError):
            parse_gold_api_payload({"symbol": "XAU"})

    def test_parse_oanda_price_payload_uses_bid_ask_mid(self):
        quote = parse_oanda_price_payload(
            {
                "instrument": "XAU_USD",
                "time": "2026-05-15T05:05:48.272079801Z",
                "bids": [{"price": "4613.40", "liquidity": 1000000}],
                "asks": [{"price": "4613.80", "liquidity": 1000000}],
            }
        )
        self.assertEqual(quote.provider, "oanda")
        self.assertEqual(quote.feed_type, "streaming")
        self.assertEqual(quote.instrument, "XAU_USD")
        self.assertAlmostEqual(quote.price, 4613.60)
        self.assertAlmostEqual(quote.bid, 4613.40)
        self.assertAlmostEqual(quote.ask, 4613.80)


if __name__ == "__main__":
    unittest.main()
