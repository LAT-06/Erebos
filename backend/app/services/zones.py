from __future__ import annotations

from dataclasses import dataclass

from app.services.data_loader import Candle
from app.services.indicators import atr


@dataclass(frozen=True)
class Zone:
    kind: str
    price: float
    strength: int
    first_time: int
    last_time: int

    def to_api(self) -> dict:
        return {
            "kind": self.kind,
            "price": round(self.price, 4),
            "strength": self.strength,
            "first_time": self.first_time,
            "last_time": self.last_time,
        }


def _cluster(levels: list[tuple[str, float, int]], tolerance: float) -> list[Zone]:
    zones: list[Zone] = []
    for kind, price, ts in sorted(levels, key=lambda item: item[1]):
        matched_idx: int | None = None
        for idx, zone in enumerate(zones):
            if zone.kind == kind and abs(zone.price - price) <= tolerance:
                matched_idx = idx
                break
        if matched_idx is None:
            zones.append(Zone(kind=kind, price=price, strength=1, first_time=ts, last_time=ts))
        else:
            zone = zones[matched_idx]
            strength = zone.strength + 1
            blended_price = ((zone.price * zone.strength) + price) / strength
            zones[matched_idx] = Zone(
                kind=kind,
                price=blended_price,
                strength=strength,
                first_time=min(zone.first_time, ts),
                last_time=max(zone.last_time, ts),
            )
    return zones


def detect_zones(candles: list[Candle], lookback: int = 3, max_zones: int = 18) -> list[Zone]:
    if len(candles) < (lookback * 2) + 1:
        return []

    scan = candles[-900:]
    atr_values = atr(scan, 14)
    latest_atr = next((value for value in reversed(atr_values) if value is not None), None)
    current_price = scan[-1].close
    tolerance = max((latest_atr or 0) * 0.35, current_price * 0.0008)

    levels: list[tuple[str, float, int]] = []
    for idx in range(lookback, len(scan) - lookback):
        window = scan[idx - lookback : idx + lookback + 1]
        candle = scan[idx]
        if candle.high == max(item.high for item in window):
            levels.append(("resistance", candle.high, candle.timestamp))
            levels.append(("liquidity_high", candle.high, candle.timestamp))
        if candle.low == min(item.low for item in window):
            levels.append(("support", candle.low, candle.timestamp))
            levels.append(("liquidity_low", candle.low, candle.timestamp))

    zones = _cluster(levels, tolerance)
    zones.sort(key=lambda zone: (zone.strength, zone.last_time), reverse=True)
    return zones[:max_zones]


def nearest_zones(price: float, zones: list[Zone]) -> dict:
    response: dict[str, dict | None] = {
        "nearest_support": None,
        "nearest_resistance": None,
        "nearest_liquidity": None,
    }

    supports = [zone for zone in zones if zone.kind in {"support", "liquidity_low"} and zone.price <= price]
    resistances = [zone for zone in zones if zone.kind in {"resistance", "liquidity_high"} and zone.price >= price]
    liquidity = [zone for zone in zones if zone.kind.startswith("liquidity")]

    if supports:
        zone = min(supports, key=lambda item: abs(item.price - price))
        response["nearest_support"] = zone.to_api() | {"distance": round(price - zone.price, 4)}
    if resistances:
        zone = min(resistances, key=lambda item: abs(item.price - price))
        response["nearest_resistance"] = zone.to_api() | {"distance": round(zone.price - price, 4)}
    if liquidity:
        zone = min(liquidity, key=lambda item: abs(item.price - price))
        response["nearest_liquidity"] = zone.to_api() | {"distance": round(abs(zone.price - price), 4)}

    return response

