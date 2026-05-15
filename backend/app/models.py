from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CandleOut(BaseModel):
    time: int
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class SetupPredictionRequest(BaseModel):
    symbol: str = "XAU"
    timeframe: str = "15m"
    side: Literal["long", "short"]
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    horizon_minutes: int = Field(default=240, ge=1, le=60 * 24 * 30)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("timeframe")
    @classmethod
    def normalize_timeframe(cls, value: str) -> str:
        return value.strip()


class PredictionOut(BaseModel):
    symbol: str
    timeframe: str
    side: str
    win_probability: float
    calibrated_confidence: float
    risk_reward: float
    verdict: Literal["avoid", "watch", "valid"]
    context: dict
    model_source: str

