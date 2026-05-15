const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

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

export function fetchCandles({ symbol, timeframe, limit = 700 }) {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  return request(`/api/candles?${params.toString()}`);
}

export function fetchIndicators({ symbol, timeframe, limit = 700 }) {
  const params = new URLSearchParams({ symbol, timeframe, limit: String(limit) });
  return request(`/api/indicators?${params.toString()}`);
}

export function predictSetup(payload) {
  return request("/api/predict/setup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function replayUrl({ symbol, timeframe, limit = 240, intervalMs = 450 }) {
  const params = new URLSearchParams({
    symbol,
    timeframe,
    limit: String(limit),
    interval_ms: String(intervalMs),
  });
  return `${API_BASE}/api/replay/stream?${params.toString()}`;
}

