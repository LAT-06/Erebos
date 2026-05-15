const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8001";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }

  return response.json();
}

export function fetchLiveQuote({ symbol }) {
  const params = new URLSearchParams({ symbol });
  return request(`/api/live/quote?${params.toString()}`);
}

export function fetchCandles({ symbol, timeframe, limit = 700, realtime = false }) {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit), realtime: String(realtime) });
  return request(`/api/candles?${params.toString()}`);
}

export function fetchIndicators({ symbol, timeframe, limit = 700, realtime = false }) {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit), realtime: String(realtime) });
  return request(`/api/indicators?${params.toString()}`);
}

export function fetchZones({ symbol, timeframes, limit = 900, realtime = false }) {
  const params = new URLSearchParams({
    symbol,
    timeframes: timeframes.join(","),
    limit: String(limit),
    realtime: String(realtime),
  });
  return request(`/api/zones?${params.toString()}`);
}

export function predictSetup(payload) {
  return request("/api/predict/setup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchModelStatus() {
  return request("/api/model/status");
}

export function fetchSetupSuggestions({ symbol, timeframe, side, horizonMinutes, realtime = false, maxSuggestions = 6 }) {
  const params = new URLSearchParams({
    symbol,
    timeframe,
    side,
    realtime: String(realtime),
    max_suggestions: String(maxSuggestions),
  });
  if (horizonMinutes) {
    params.set("horizon_minutes", String(horizonMinutes));
  }
  return request(`/api/setups/suggest?${params.toString()}`);
}

export function replayUrl({ symbol, timeframe, limit = 240, intervalMs = 450, realtime = false }) {
  const params = new URLSearchParams({
    symbol,
    timeframe,
    limit: String(limit),
    interval_ms: String(intervalMs),
    realtime: String(realtime),
  });
  return `${API_BASE}/api/replay/stream?${params.toString()}`;
}

export function liveUrl({ symbol, timeframe, intervalMs = 1000 }) {
  const params = new URLSearchParams({
    symbol,
    timeframe,
    interval_ms: String(intervalMs),
  });
  return `${API_BASE}/api/live/stream?${params.toString()}`;
}
