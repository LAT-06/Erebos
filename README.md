# XAU Trading Platform MVP

This repo now contains the first XAU-only trading platform scaffold:

- FastAPI backend for candles, EMA/RSI indicators, liquidity/support/resistance zones, setup prediction, and CSV replay.
- React + TradingView Lightweight Charts frontend for charting and setup review.
- Kaggle-ready notebook for multi-timeframe XAU model training.

## Project Layout

```text
backend/                  FastAPI app and tests
frontend/                 React chart app
dataset/xau/              XAU CSV files
notebook/xau/             Kaggle training notebook
models/                   Optional exported model artifacts
```

## Run The Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The API will be available at `http://localhost:8001`, which matches the frontend default.

## Live XAU Data

The charting library only renders data; it does not include TradingView market data. By default, Live mode uses the free `gold-api.com` XAU quote as a snapshot fallback, so it may update slower than TradingView during fast markets.

For a true streaming feed, configure OANDA before starting the backend:

```bash
export LIVE_PRICE_PROVIDER=oanda
export OANDA_ENV=practice
export OANDA_ACCESS_TOKEN=your_token
export OANDA_ACCOUNT_ID=your_account_id
export OANDA_INSTRUMENT_XAU=XAU_USD
```

Then `/api/live/stream` uses OANDA's streaming pricing endpoint. Without those credentials, the backend cannot legally mirror TradingView's realtime feed.

## Run The Frontend

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:5173`.

## Train The Model

Open `notebook/xau/xau_multitimeframe_training.ipynb` on Kaggle, attach the XAU dataset folder, and run all cells. The notebook exports:

- `xau_setup_model.joblib`
- `xau_setup_feature_config.json`

Copy the model artifact into `models/xau_setup_model.joblib`, or set `MODEL_PATH=/path/to/xau_setup_model.joblib` before starting the backend.

Until a trained artifact exists, `/api/predict/setup` uses a transparent heuristic fallback so the platform can be tested end-to-end.
With `models/xau_setup_model.joblib` present and LightGBM installed, the backend uses the trained model directly.

## API Surface

- `GET /api/candles?symbol=XAU&timeframe=15m&from=&to=`
- `GET /api/indicators?symbol=XAU&timeframe=15m`
- `POST /api/predict/setup`
- `GET /api/setups/suggest?symbol=XAU&timeframe=15m&side=long`
- `GET /api/model/status`
- `POST /api/model/reload`
- `GET /api/replay/stream`
- `GET /api/live/quote`
- `GET /api/live/status`
- `GET /api/live/stream`

`realtime=true` shifts the latest CSV window to the current local time and scales it to the active live quote. `gold-api.com` is a snapshot fallback; OANDA is the streaming adapter when configured.

## Verification

```bash
cd backend
python -m unittest discover -s tests
```
