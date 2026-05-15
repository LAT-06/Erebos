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
  fetchLiveQuote,
  fetchModelStatus,
  fetchSetupSuggestions,
  fetchZones,
  liveUrl,
  predictSetup,
  replayUrl,
} from "./api.js";

const TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"];
const SYMBOLS = ["XAU"];
const PRICE_AXIS_HITBOX = 76;

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

function formatCompact(value) {
  if (!Number.isFinite(value)) return "--";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000_000) return `${(value / 1_000_000_000_000).toFixed(1)}T`;
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

function isResistanceZone(zone) {
  return zone.kind.includes("resistance") || zone.kind.includes("high");
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

export default function App() {
  const [symbol, setSymbol] = useState("XAU");
  const [timeframe, setTimeframe] = useState("15m");
  const [mode, setMode] = useState("static");
  const [liveQuote, setLiveQuote] = useState(null);
  const [candles, setCandles] = useState([]);
  const [indicators, setIndicators] = useState({ emas: {}, rsi: [], zones: [], latest: {} });
  const [setup, setSetup] = useState(defaultSetup(null));
  const [prediction, setPrediction] = useState(null);
  const [modelStatus, setModelStatus] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [suggesting, setSuggesting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [zoneRects, setZoneRects] = useState([]);

  const chartEl = useRef(null);
  const rsiEl = useRef(null);
  const chartState = useRef(null);
  const fitNextDataRef = useRef(true);
  const liveIncrementalRef = useRef(false);
  const priceScaleMarginRef = useRef(0.12);
  const latestRefs = useRef({ zones: [], lastCandle: null, indicators: {}, timeframe: "15m" });

  const lastCandle = candles[candles.length - 1];
  const zones = indicators.zones || [];
  const liquidityStats = useMemo(
    () =>
      zones
        .filter((zone) => zone.kind.includes("liquidity"))
        .filter((zone) => !zone.timeframe || zone.timeframe === timeframe)
        .filter((zone) => zone.active !== false)
        .sort((a, b) => (b.volume || 0) - (a.volume || 0))
        .slice(0, 5),
    [zones, timeframe],
  );

  latestRefs.current = {
    zones,
    lastCandle,
    indicators,
    timeframe,
  };

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
      const [nextCandles, nextIndicators, nextQuote] = await Promise.all([
        fetchCandles({ symbol, timeframe, limit: 700, realtime }),
        fetchIndicators({ symbol, timeframe, limit: 700, realtime }),
        realtime ? fetchLiveQuote({ symbol }) : Promise.resolve(null),
      ]);
      fitNextDataRef.current = true;
      setCandles(nextCandles);
      setIndicators({ ...nextIndicators, zones: nextIndicators.zones || [] });
      setLiveQuote(nextQuote || nextIndicators.live_quote || null);
      setPrediction(null);
      setSuggestions([]);
      if (nextCandles.length) {
        setSetup(defaultSetup(nextCandles[nextCandles.length - 1], setup.side));
      }
      fetchZones({ symbol, timeframes: [timeframe], limit: 360, realtime })
        .then((nextZones) => {
          setIndicators((current) => ({ ...current, zones: nextZones.zones || [] }));
          setLiveQuote((current) => nextZones.live_quote || current);
        })
        .catch((err) => setError(err.message));
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

    const source = new EventSource(liveUrl({ symbol, timeframe, intervalMs: 1000 }));
    source.onmessage = (event) => {
      const candle = JSON.parse(event.data);
      if (candle.quote) {
        setLiveQuote(candle.quote);
      }
      chartState.current?.candleSeries.update({
        time: candle.time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
      liveIncrementalRef.current = true;
      setCandles((current) => {
        const withoutDuplicate = current.filter((item) => item.time !== candle.time);
        return [...withoutDuplicate, candle].sort((a, b) => a.time - b.time).slice(-700);
      });
    };
    source.onerror = () => source.close();

    const contextTimer = window.setInterval(async () => {
      try {
        const [nextIndicators, nextZones] = await Promise.all([
          fetchIndicators({ symbol, timeframe, limit: 700, realtime: true }),
          fetchZones({ symbol, timeframes: [timeframe], limit: 360, realtime: true }),
        ]);
        setIndicators({ ...nextIndicators, zones: nextZones.zones || [] });
        setLiveQuote(nextIndicators.live_quote || nextZones.live_quote || null);
      } catch (err) {
        setError(err.message);
      }
    }, 30000);

    return () => {
      source.close();
      window.clearInterval(contextTimer);
    };
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

  function recalculateZoneRects() {
    const state = chartState.current;
    const { zones: currentZones, lastCandle: currentLastCandle, indicators: currentIndicators, timeframe: currentTimeframe } =
      latestRefs.current;
    if (!state || !chartEl.current || !currentLastCandle) {
      setZoneRects([]);
      return;
    }

    const plotWidth = chartEl.current.clientWidth - PRICE_AXIS_HITBOX;
    const atr = currentIndicators.latest?.atr || Math.max(currentLastCandle.close * 0.01, 1);
    const visibleRange = Math.max(atr * 14, currentLastCandle.close * 0.06);
    const currentX = state.chart.timeScale().timeToCoordinate(currentLastCandle.time);
    const selectedZones = currentZones
      .filter((zone) => zone.kind === "support" || zone.kind === "resistance")
      .filter((zone) => !zone.timeframe || zone.timeframe === currentTimeframe)
      .filter((zone) => zone.active !== false)
      .filter((zone) => Math.abs(zone.price - currentLastCandle.close) <= visibleRange)
      .sort((a, b) => {
        return (b.strength || 0) - (a.strength || 0);
      })
      .slice(0, 10);

    const nextRects = selectedZones
      .map((zone, index) => {
        const topPrice = zone.top || zone.price;
        const bottomPrice = zone.bottom || zone.price;
        const yTop = state.candleSeries.priceToCoordinate(topPrice);
        const yBottom = state.candleSeries.priceToCoordinate(bottomPrice);
        const xStart = state.chart.timeScale().timeToCoordinate(zone.last_time || zone.first_time);
        const xEnd = currentX === null ? null : Math.min(plotWidth, currentX + 24);
        if (yTop === null || yBottom === null || xStart === null || xEnd === null) return null;
        const top = Math.min(yTop, yBottom);
        const height = Math.max(Math.abs(yBottom - yTop), 5);
        const left = clamp(Math.min(xStart, xEnd), 0, plotWidth);
        const width = Math.max(Math.abs(xEnd - left), 8);
        return {
          id: `${zone.timeframe}-${zone.kind}-${zone.price}-${index}`,
          kind: zone.kind,
          left,
          width,
          top,
          height,
        };
      })
      .filter(Boolean);

    setZoneRects(nextRects);
  }

  useEffect(() => {
    if (!chartEl.current || !rsiEl.current) return undefined;

    const chart = createChart(chartEl.current, {
      width: chartEl.current.clientWidth,
      height: chartEl.current.clientHeight,
      layout: {
        background: { color: "#131722" },
        textColor: "#d1d4dc",
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "#1f2430" },
        horzLines: { color: "#1f2430" },
      },
      rightPriceScale: { borderColor: "#2a2e39" },
      timeScale: { borderColor: "#2a2e39", timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    });

    const rsiChart = createChart(rsiEl.current, {
      width: rsiEl.current.clientWidth,
      height: rsiEl.current.clientHeight,
      layout: {
        background: { color: "#131722" },
        textColor: "#787b86",
        fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      },
      grid: {
        vertLines: { color: "#1f2430" },
        horzLines: { color: "#1f2430" },
      },
      rightPriceScale: { visible: false, borderColor: "#2a2e39", scaleMargins: { top: 0.16, bottom: 0.18 } },
      timeScale: { visible: false, borderColor: "#2a2e39", timeVisible: false, secondsVisible: false },
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
    const ema99 = chart.addLineSeries({ color: "#2962ff", lineWidth: 2, title: "EMA 99" });
    const ema200 = chart.addLineSeries({ color: "#ab47bc", lineWidth: 2, title: "EMA 200" });
    const rsiSeries = rsiChart.addLineSeries({ color: "#7e57c2", lineWidth: 2, title: "RSI 14" });
    const rsi70 = rsiChart.addLineSeries({ color: "rgba(239,83,80,0.45)", lineWidth: 1, lineStyle: LineStyle.Dashed });
    const rsi30 = rsiChart.addLineSeries({ color: "rgba(38,166,154,0.45)", lineWidth: 1, lineStyle: LineStyle.Dashed });

    chartState.current = { chart, rsiChart, candleSeries, ema25, ema99, ema200, rsiSeries, rsi70, rsi30 };

    const syncZones = () => window.requestAnimationFrame(recalculateZoneRects);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncZones);

    const wheelPriceScale = (event) => {
      if (!chartEl.current) return;
      const rect = chartEl.current.getBoundingClientRect();
      const inPriceScale = event.clientX >= rect.right - PRICE_AXIS_HITBOX;
      if (!inPriceScale) return;
      event.preventDefault();
      const nextMargin = clamp(priceScaleMarginRef.current + (event.deltaY > 0 ? 0.025 : -0.025), 0.02, 0.32);
      priceScaleMarginRef.current = nextMargin;
      chart.priceScale("right").applyOptions({
        scaleMargins: {
          top: nextMargin,
          bottom: nextMargin,
        },
      });
      syncZones();
    };
    chartEl.current.addEventListener("wheel", wheelPriceScale, { passive: false });

    const resize = () => {
      if (!chartEl.current || !rsiEl.current) return;
      chart.applyOptions({ width: chartEl.current.clientWidth, height: chartEl.current.clientHeight });
      rsiChart.applyOptions({ width: rsiEl.current.clientWidth, height: rsiEl.current.clientHeight });
      syncZones();
    };
    window.addEventListener("resize", resize);
    window.requestAnimationFrame(resize);

    return () => {
      window.removeEventListener("resize", resize);
      chartEl.current?.removeEventListener("wheel", wheelPriceScale);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncZones);
      chart.remove();
      rsiChart.remove();
      chartState.current = null;
    };
  }, []);

  useEffect(() => {
    const state = chartState.current;
    if (!state) return;

    if (liveIncrementalRef.current) {
      liveIncrementalRef.current = false;
      window.requestAnimationFrame(recalculateZoneRects);
      return;
    }

    state.candleSeries.setData(candleData);
    if (fitNextDataRef.current && candleData.length) {
      state.chart.timeScale().fitContent();
      state.rsiChart.timeScale().fitContent();
      fitNextDataRef.current = false;
    }
    window.requestAnimationFrame(recalculateZoneRects);
  }, [candleData]);

  useEffect(() => {
    const state = chartState.current;
    if (!state) return;

    state.ema25.setData(indicators.emas?.ema_25 || []);
    state.ema99.setData(indicators.emas?.ema_99 || []);
    state.ema200.setData(indicators.emas?.ema_200 || []);
    state.rsiSeries.setData(indicators.rsi || []);
    state.rsi70.setData(candleData.map((item) => ({ time: item.time, value: 70 })));
    state.rsi30.setData(candleData.map((item) => ({ time: item.time, value: 30 })));
    window.requestAnimationFrame(recalculateZoneRects);
  }, [candleData, indicators]);

  useEffect(() => {
    if (mode !== "replay") return undefined;

    fitNextDataRef.current = true;
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
          <span className="sourcePill">
            {mode === "live"
              ? `Live ${liveQuote?.feed_type === "streaming" ? "Stream" : "Snapshot"} ${liveQuote?.provider || "market"} ${roundPrice(liveQuote?.price || lastCandle?.close)}`
              : mode === "replay" ? "Replay" : "Historical"}
          </span>
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
              <span>{timeframe} candles / {timeframe} zones only</span>
            </div>
            <div className="legend">
              <span className="ema25">EMA 25</span>
              <span className="ema99">EMA 99</span>
              <span className="ema200">EMA 200</span>
              <span className="zones">Zones {zones.length}</span>
            </div>
          </div>
          <div className="chartStack">
            <div className="chartCanvas" ref={chartEl} />
            <div className="zoneOverlay" aria-hidden="true">
              {zoneRects.map((zone) => (
                <div
                  className={`zoneBand ${isResistanceZone(zone) ? "resistance" : "support"}`}
                  key={zone.id}
                  style={{ left: `${zone.left}px`, top: `${zone.top}px`, width: `${zone.width}px`, height: `${zone.height}px` }}
                />
              ))}
            </div>
            <div className="liquidityCorner">
              <div className="cornerTitle">Liquidity map · {timeframe}</div>
              {liquidityStats.length ? (
                liquidityStats.map((zone) => (
                  <div className="liqRow" key={`${zone.timeframe}-${zone.kind}-${zone.price}`}>
                    <span>{zone.timeframe} {zone.kind.replace("liquidity_", "")}</span>
                    <strong>{roundPrice(zone.price)}</strong>
                    <em>{formatCompact(zone.volume)} vol</em>
                  </div>
                ))
              ) : (
                <div className="liqRow">
                  <span>No zone volume</span>
                </div>
              )}
            </div>
          </div>
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
              <p>
                {(indicators.zones || []).filter((zone) => !zone.timeframe || zone.timeframe === timeframe).length} {timeframe} zones
                detected on the current window.
              </p>
            )}
          </section>
        </aside>
      </section>
    </main>
  );
}
