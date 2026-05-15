from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = Path(os.getenv("DATASET_ROOT", PROJECT_ROOT / "dataset"))
MODEL_PATH = Path(os.getenv("MODEL_PATH", PROJECT_ROOT / "models" / "xau_setup_model.joblib"))

SUPPORTED_SYMBOLS = {"XAU"}

TIMEFRAME_FILES = {
    "1m": "XAU_1m_data.csv",
    "5m": "XAU_5m_data.csv",
    "15m": "XAU_15m_data.csv",
    "30m": "XAU_30m_data.csv",
    "1h": "XAU_1h_data.csv",
    "4h": "XAU_4h_data.csv",
    "1d": "XAU_1d_data.csv",
    "1w": "XAU_1w_data.csv",
    "1M": "XAU_1Month_data.csv",
}

TIMEFRAME_ALIASES = {
    "1month": "1M",
    "1mo": "1M",
    "1mth": "1M",
    "month": "1M",
}

DEFAULT_LIMIT = 700
MAX_LIMIT = 5000

