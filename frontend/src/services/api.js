import { SAMPLE_CASES } from './mockData';

const DEFAULT_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function checkBackendHealth(baseUrl = DEFAULT_API_URL) {
  const cleanUrl = baseUrl.replace(/\/+$/, '');
  const startTime = performance.now();
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const res = await fetch(`${cleanUrl}/health`, {
      method: 'GET',
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    const duration = Math.round(performance.now() - startTime);
    if (!res.ok) {
      return { online: false, status: res.status, latencyMs: duration, error: `HTTP ${res.status}` };
    }
    const data = await res.json();
    return { online: data.status === 'ok', status: res.status, latencyMs: duration, data };
  } catch (err) {
    const duration = Math.round(performance.now() - startTime);
    return { online: false, latencyMs: duration, error: err.name === 'AbortError' ? 'Timeout (4s)' : err.message };
  }
}

export async function optimizeEnergy(payload, { baseUrl = DEFAULT_API_URL, useMock = false } = {}) {
  const startTime = performance.now();

  if (useMock) {
    // Return matching mock scenario or synthesized mock
    await new Promise(r => setTimeout(r, 650)); // realistic demo latency
    const matched = SAMPLE_CASES.find(c => c.input?.scenario_id === payload.scenario_id);
    const latencyMs = Math.round(performance.now() - startTime);

    if (matched && matched.expected_output) {
      return {
        success: true,
        data: matched.expected_output,
        latencyMs,
        source: 'mock',
      };
    }

    // Fallback mock using case 1 format
    const fallback = JSON.parse(JSON.stringify(SAMPLE_CASES[0].expected_output));
    fallback.scenario_id = payload.scenario_id || 'CUSTOM-01';
    return {
      success: true,
      data: fallback,
      latencyMs,
      source: 'mock',
    };
  }

  const cleanUrl = baseUrl.replace(/\/+$/, '');
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s per rubric

    const res = await fetch(`${cleanUrl}/optimize-energy`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    const latencyMs = Math.round(performance.now() - startTime);

    if (!res.ok) {
      let errDetail = `HTTP ${res.status}`;
      try {
        const errJson = await res.json();
        errDetail = errJson.detail || errJson.message || JSON.stringify(errJson);
      } catch {
        // use default
      }
      return {
        success: false,
        error: `Server responded with ${errDetail}`,
        status: res.status,
        latencyMs,
      };
    }

    const data = await res.json();
    return {
      success: true,
      data,
      latencyMs,
      source: 'live',
    };
  } catch (err) {
    const latencyMs = Math.round(performance.now() - startTime);
    return {
      success: false,
      error: err.name === 'AbortError' ? 'Request timed out after 30s' : `Connection error: ${err.message}`,
      latencyMs,
    };
  }
}
