import { useEffect, useMemo, useRef, useState } from "react";
import { createChart, CrosshairMode, LineStyle } from "lightweight-charts";
import {
  Activity,
  BarChart3,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
  Waves,
} from "lucide-react";
import {
  fetchCandles,
  fetchIndicators,
  fetchModelStatus,
  fetchSetupSuggestions,
  predictSetup,
  replayUrl,
} from "./api.js";

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];
const SYMBOLS = ["XAU"];

function roundPrice(value) {
  if (!Number.isFinite(value)) return "";
  return value.toFixed(2);
}

function defaultSetup(lastCandle, side = "long") {
  const entry = lastCandle?.close || 0;
  const range = Math.max((lastCandle?.high || entry) - (lastCandle?.low || entry), entry * 0.002, 1);
  return side === "long"
    ? {
        side,
        entry: roundPrice(entry),
        stop_loss: roundPrice(entry - range * 1.2),
        take_profit: roundPrice(entry + range * 2.0),
        horizon_minutes: 240,
      }
    : {
        side,
        entry: roundPrice(entry),
        stop_loss: roundPrice(entry + range * 1.2),
        take_profit: roundPrice(entry - range * 2.0),
        horizon_minutes: 240,
      };
}

function verdictLabel(verdict) {
  if (verdict === "valid") return "Valid";
  if (verdict === "watch") return "Watch";
  return "Avoid";
}

export default function App() {
  const [symbol, setSymbol] = useState("XAU");
  const [timeframe, setTimeframe] = useState("15m");
  const [mode, setMode] = useState("static");
  const [candles, setCandles] = useState([]);
  const [indicators, setIndicators] = useState({ emas: {}, rsi: [], zones: [], latest: {} });
  const [setup, setSetup] = useState(defaultSetup(null));
  const [prediction, setPrediction] = useState(null);
  const [modelStatus, setModelStatus] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const chartEl = useRef(null);
  const rsiEl = useRef(null);
  const chartState = useRef(null);
  const priceLines = useRef([]);

  const lastCandle = candles[candles.length - 1];

  const candleData = useMemo(
    () =>
      [...candles]
        .sort((a, b) => a.time - b.time)
        .map((candle) => ({
          time: candle.time,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        })),
    [candles],
  );

  async function loadMarketData() {
    setLoading(true);
    setError("");
    try {
      const realtime = mode === "live";
      const [nextCandles, nextIndicators] = await Promise.all([
        fetchCandles({ symbol, timeframe, limit: 700, realtime }),
        fetchIndicators({ symbol, timeframe, limit: 700, realtime }),
      ]);
      setCandles(nextCandles);
      setIndicators(nextIndicators);
      setPrediction(null);
      setSuggestions([]);
      if (nextCandles.length) {
        setSetup(defaultSetup(nextCandles[nextCandles.length - 1], setup.side));
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function submitPrediction(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await predictSetup({
        symbol,
        timeframe,
        side: setup.side,
        entry: Number(setup.entry),
        stop_loss: Number(setup.stop_loss),
        take_profit: Number(setup.take_profit),
        horizon_minutes: Number(setup.horizon_minutes),
        realtime: mode === "live",
      });
      setPrediction(result);
    } catch (err) {
      setError(err.message);
      setPrediction(null);
    } finally {
      setLoading(false);
    }
  }

  function updateSetup(field, value) {
    setSetup((current) => ({ ...current, [field]: value }));
  }

  function switchSide(side) {
    setSetup(defaultSetup(lastCandle, side));
    setPrediction(null);
    setSuggestions([]);
  }

  useEffect(() => {
    fetchModelStatus()
      .then(setModelStatus)
      .catch((err) => setModelStatus({ loaded: false, error: err.message }));
  }, []);

  useEffect(() => {
    if (mode !== "replay") {
      loadMarketData();
    }
  }, [symbol, timeframe, mode]);

  useEffect(() => {
    if (mode !== "live") return undefined;

    const timer = window.setInterval(() => {
      loadMarketData();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [mode, symbol, timeframe]);

  async function loadSuggestions() {
    setSuggesting(true);
    setError("");
    try {
      const result = await fetchSetupSuggestions({
        symbol,
        timeframe,
        side: setup.side,
        horizonMinutes: Number(setup.horizon_minutes),
        realtime: mode === "live",
        maxSuggestions: 6,
      });
      setSuggestions(result);
      if (result[0]) {
        applySuggestion(result[0]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setSuggesting(false);
    }
  }

  function applySuggestion(suggestion) {
    setSetup({
      side: suggestion.side,
      entry: roundPrice(suggestion.entry),
      stop_loss: roundPrice(suggestion.stop_loss),
      take_profit: roundPrice(suggestion.take_profit),
      horizon_minutes: suggestion.horizon_minutes,
    });
    setPrediction({
      win_probability: suggestion.win_probability,
      calibrated_confidence: suggestion.calibrated_confidence,
      risk_reward: suggestion.risk_reward,
      verdict: suggestion.verdict,
      model_source: suggestion.model_source,
      context: {},
    });
  }

  useEffect(() => {
    if (!chartEl.current || !rsiEl.current) return undefined;

    const chart = createChart(chartEl.current, {
      width: chartEl.current.clientWidth,
      height: chartEl.current.clientHeight,
      layout: {
        background: { color: "#f8f5ef" },
        textColor: "#2a2723",
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "#e8dfd2" },
        horzLines: { color: "#e8dfd2" },
      },
      rightPriceScale: { borderColor: "#cdbfabe6" },
      timeScale: { borderColor: "#cdbfabe6", timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const rsiChart = createChart(rsiEl.current, {
      width: rsiEl.current.clientWidth,
      height: rsiEl.current.clientHeight,
      layout: {
        background: { color: "#fbfaf7" },
        textColor: "#403a33",
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "#eee7dc" },
        horzLines: { color: "#eee7dc" },
      },
      rightPriceScale: { borderColor: "#d7caba", scaleMargins: { top: 0.16, bottom: 0.18 } },
      timeScale: { borderColor: "#d7caba", timeVisible: true, secondsVisible: false },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#1f9d75",
      downColor: "#c0473d",
      borderUpColor: "#1f9d75",
      borderDownColor: "#c0473d",
      wickUpColor: "#1f9d75",
      wickDownColor: "#c0473d",
    });
    const ema25 = chart.addLineSeries({ color: "#d59b23", lineWidth: 2, title: "EMA 25" });
    const ema99 = chart.addLineSeries({ color: "#2d7dd2", lineWidth: 2, title: "EMA 99" });
    const ema200 = chart.addLineSeries({ color: "#6d597a", lineWidth: 2, title: "EMA 200" });
    const rsiSeries = rsiChart.addLineSeries({ color: "#4f6f52", lineWidth: 2, title: "RSI 14" });
    const rsi70 = rsiChart.addLineSeries({ color: "#c0473d", lineWidth: 1, lineStyle: LineStyle.Dashed });
    const rsi30 = rsiChart.addLineSeries({ color: "#1f9d75", lineWidth: 1, lineStyle: LineStyle.Dashed });

    chartState.current = { chart, rsiChart, candleSeries, ema25, ema99, ema200, rsiSeries, rsi70, rsi30 };

    const resize = () => {
      if (!chartEl.current || !rsiEl.current) return;
      chart.applyOptions({ width: chartEl.current.clientWidth, height: chartEl.current.clientHeight });
      rsiChart.applyOptions({ width: rsiEl.current.clientWidth, height: rsiEl.current.clientHeight });
    };
    const observer = new ResizeObserver(resize);
    observer.observe(chartEl.current);
    observer.observe(rsiEl.current);

    return () => {
      observer.disconnect();
      chart.remove();
      rsiChart.remove();
      chartState.current = null;
    };
  }, []);

  useEffect(() => {
    const state = chartState.current;
    if (!state) return;

    state.candleSeries.setData(candleData);
    state.ema25.setData(indicators.emas?.ema_25 || []);
    state.ema99.setData(indicators.emas?.ema_99 || []);
    state.ema200.setData(indicators.emas?.ema_200 || []);
    state.rsiSeries.setData(indicators.rsi || []);
    state.rsi70.setData(candleData.map((item) => ({ time: item.time, value: 70 })));
    state.rsi30.setData(candleData.map((item) => ({ time: item.time, value: 30 })));

    priceLines.current.forEach((line) => state.candleSeries.removePriceLine(line));
    priceLines.current = (indicators.zones || []).slice(0, 12).map((zone) =>
      state.candleSeries.createPriceLine({
        price: zone.price,
        color: zone.kind.includes("resistance") || zone.kind.includes("high") ? "#b5483e" : "#27825f",
        lineWidth: Math.min(3, Math.max(1, zone.strength)),
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: zone.kind.replace("_", " "),
      }),
    );

    state.chart.timeScale().fitContent();
    state.rsiChart.timeScale().fitContent();
  }, [candleData, indicators]);

  useEffect(() => {
    if (mode !== "replay") return undefined;

    setCandles([]);
    chartState.current?.candleSeries.setData([]);
    const source = new EventSource(replayUrl({ symbol, timeframe, limit: 240, intervalMs: 450 }));
    source.onmessage = (event) => {
      const candle = JSON.parse(event.data);
      setCandles((current) => {
        const withoutDuplicate = current.filter((item) => item.time !== candle.time);
        return [...withoutDuplicate, candle].sort((a, b) => a.time - b.time).slice(-700);
      });
    };
    source.onerror = () => source.close();

    return () => source.close();
  }, [mode, symbol, timeframe]);

  const probability = prediction ? Math.round(prediction.win_probability * 100) : null;

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <BarChart3 size={22} aria-hidden="true" />
          <div>
            <h1>XAU Trading Platform</h1>
            <span>{lastCandle ? `${lastCandle.datetime} close ${roundPrice(lastCandle.close)}` : "Loading market data"}</span>
          </div>
        </div>

        <div className="toolbar" aria-label="Market controls">
          <span className={modelStatus?.loaded ? "sourcePill model" : "sourcePill warning"}>
            {modelStatus?.loaded ? `Model ${modelStatus.model_kind || "loaded"}` : "Model unavailable"}
          </span>
          <span className="sourcePill">{mode === "live" ? "CSV realtime sim" : mode === "replay" ? "Replay" : "Historical"}</span>
          <select value={symbol} onChange={(event) => setSymbol(event.target.value)} aria-label="Symbol">
            {SYMBOLS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <div className="segmented" aria-label="Timeframe">
            {TIMEFRAMES.map((item) => (
              <button
                key={item}
                className={timeframe === item ? "active" : ""}
                onClick={() => setTimeframe(item)}
                type="button"
              >
                {item}
              </button>
            ))}
          </div>
          <button className="iconButton" onClick={loadMarketData} type="button" title="Refresh market data">
            <RefreshCw size={17} aria-hidden="true" />
          </button>
          <div className="modeGroup" aria-label="Data mode">
            <button className={mode === "static" ? "active" : ""} onClick={() => setMode("static")} type="button">
              Static
            </button>
            <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")} type="button">
              <Activity size={14} aria-hidden="true" />
              Live
            </button>
            <button className={mode === "replay" ? "active" : ""} onClick={() => setMode("replay")} type="button">
              {mode === "replay" ? <Pause size={14} aria-hidden="true" /> : <Play size={14} aria-hidden="true" />}
              Replay
            </button>
          </div>
        </div>
      </header>

      {error ? (
        <div className="error" role="alert">
          <ShieldAlert size={17} aria-hidden="true" />
          {error}
        </div>
      ) : null}

      <section className="workspace">
        <div className="chartArea">
          <div className="chartHeader">
            <div>
              <strong>{symbol}</strong>
              <span>{timeframe} candles</span>
            </div>
            <div className="legend">
              <span className="ema25">EMA 25</span>
              <span className="ema99">EMA 99</span>
              <span className="ema200">EMA 200</span>
              <span className="zones">Zones</span>
            </div>
          </div>
          <div className="chartCanvas" ref={chartEl} />
          <div className="rsiPanel">
            <div className="rsiTitle">
              <Activity size={14} aria-hidden="true" />
              RSI 14
              <span>{indicators.latest?.rsi ?? "--"}</span>
            </div>
            <div className="rsiCanvas" ref={rsiEl} />
          </div>
        </div>

        <aside className="sidePanel">
          <form className="panel" onSubmit={submitPrediction}>
            <div className="panelTitle">
              <Waves size={18} aria-hidden="true" />
              <h2>Setup Prediction</h2>
            </div>

            <div className="sideToggle">
              <button
                type="button"
                className={setup.side === "long" ? "long active" : "long"}
                onClick={() => switchSide("long")}
              >
                <TrendingUp size={16} aria-hidden="true" />
                Long
              </button>
              <button
                type="button"
                className={setup.side === "short" ? "short active" : "short"}
                onClick={() => switchSide("short")}
              >
                <TrendingDown size={16} aria-hidden="true" />
                Short
              </button>
            </div>

            <label>
              Entry
              <input value={setup.entry} inputMode="decimal" onChange={(event) => updateSetup("entry", event.target.value)} />
            </label>
            <label>
              Stop loss
              <input
                value={setup.stop_loss}
                inputMode="decimal"
                onChange={(event) => updateSetup("stop_loss", event.target.value)}
              />
            </label>
            <label>
              Take profit
              <input
                value={setup.take_profit}
                inputMode="decimal"
                onChange={(event) => updateSetup("take_profit", event.target.value)}
              />
            </label>
            <label>
              Horizon minutes
              <input
                value={setup.horizon_minutes}
                inputMode="numeric"
                onChange={(event) => updateSetup("horizon_minutes", event.target.value)}
              />
            </label>

            <button className="primaryButton" disabled={loading} type="submit">
              {loading ? "Calculating" : "Predict setup"}
            </button>
            <button className="secondaryButton" disabled={suggesting} onClick={loadSuggestions} type="button">
              {suggesting ? "Finding limits" : "Suggest limit entry"}
            </button>
          </form>

          {suggestions.length ? (
            <section className="suggestionsPanel">
              <h2>Limit Ideas</h2>
              {suggestions.map((item, index) => (
                <button className="suggestionCard" key={`${item.side}-${item.entry}-${item.stop_loss}-${index}`} onClick={() => applySuggestion(item)} type="button">
                  <div>
                    <strong>{item.order_type.replace("_", " ")}</strong>
                    <span>{Math.round(item.win_probability * 100)}% / {item.verdict}</span>
                  </div>
                  <div>
                    <span>E {roundPrice(item.entry)}</span>
                    <span>SL {roundPrice(item.stop_loss)}</span>
                    <span>TP {roundPrice(item.take_profit)}</span>
                  </div>
                </button>
              ))}
            </section>
          ) : null}

          <section className={`result ${prediction?.verdict || ""}`}>
            <div className="resultTop">
              <span>Win probability</span>
              <strong>{probability === null ? "--" : `${probability}%`}</strong>
            </div>
            <div className="probabilityBar" aria-hidden="true">
              <span style={{ width: `${probability ?? 0}%` }} />
            </div>
            <div className="metrics">
              <div>
                <span>Verdict</span>
                <strong>{prediction ? verdictLabel(prediction.verdict) : "--"}</strong>
              </div>
              <div>
                <span>RR</span>
                <strong>{prediction?.risk_reward ?? "--"}</strong>
              </div>
              <div>
                <span>Confidence</span>
                <strong>
                  {prediction ? `${Math.round(prediction.calibrated_confidence * 100)}%` : "--"}
                </strong>
              </div>
              <div>
                <span>Source</span>
                <strong>{prediction?.model_source || "--"}</strong>
              </div>
            </div>
          </section>

          <section className="zonesPanel">
            <h2>Nearest Zones</h2>
            {prediction ? (
              ["nearest_support", "nearest_resistance", "nearest_liquidity"].map((key) => {
                const zone = prediction.context?.[key];
                return (
                  <div className="zoneRow" key={key}>
                    <span>{key.replace("nearest_", "").replace("_", " ")}</span>
                    <strong>{zone ? `${roundPrice(zone.price)} / ${roundPrice(zone.distance)}` : "--"}</strong>
                  </div>
                );
              })
            ) : (
              <p>{(indicators.zones || []).length} zones detected on the current window.</p>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}
