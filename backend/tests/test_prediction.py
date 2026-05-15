from datetime import datetime, timedelta
import unittest

from app.models import SetupPredictionRequest
from app.services.data_loader import Candle
from app.services.prediction import predict_setup, risk_reward


def make_candles(count: int = 260) -> list[Candle]:
    rows = []
    price = 1900.0
    for index in range(count):
        price += 0.5
        rows.append(
            Candle(
                symbol="XAU",
                timeframe="15m",
                dt=datetime(2024, 1, 1) + timedelta(minutes=15 * index),
                open=price - 0.2,
                high=price + 1.1,
                low=price - 1.0,
                close=price,
                volume=1000 + index,
            )
        )
    return rows


class PredictionTests(unittest.TestCase):
    def test_risk_reward_validates_long_geometry(self):
        self.assertEqual(risk_reward("long", entry=100, stop_loss=95, take_profit=110), 2.0)
        with self.assertRaises(ValueError):
            risk_reward("long", entry=100, stop_loss=101, take_profit=110)

    def test_prediction_returns_contract_with_heuristic_source(self):
        request = SetupPredictionRequest(
            symbol="XAU",
            timeframe="15m",
            side="long",
            entry=2030,
            stop_loss=2020,
            take_profit=2050,
            horizon_minutes=240,
        )
        result = predict_setup(request, make_candles(), zones=[])
        self.assertGreaterEqual(result["win_probability"], 0)
        self.assertLessEqual(result["win_probability"], 1)
        self.assertEqual(result["risk_reward"], 2.0)
        self.assertIn(result["verdict"], {"avoid", "watch", "valid"})
        self.assertIn(result["model_source"], {"heuristic", "model"})


if __name__ == "__main__":
    unittest.main()
