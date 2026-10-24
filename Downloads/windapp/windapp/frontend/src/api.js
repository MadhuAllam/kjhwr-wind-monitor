import { useEffect, useState } from "react";

const BASE = "https://kjhwr-wind-monitor.onrender.com";

/** Fetch JSON without ever throwing on empty / non-JSON bodies. Always resolves to { data } or { error }. */
export async function getJson(path) {
  let res;
  try {
    res = await fetch(BASE + path, { headers: { Accept: "application/json" } });
  } catch (e) {
    return { error: `Cannot reach the API (${e.message}). Is the backend running on 127.0.0.1:8000?` };
  }
  const text = await res.text();
  let body = null;
  if (text) {
    try { body = JSON.parse(text); } catch { /* not JSON */ }
  }
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : null;
    const hint = !text ? " - empty response; the backend is probably down or crashed (check its terminal)" : "";
    return { error: detail || `HTTP ${res.status}${hint}` };
  }
  if (body === null) return { error: "The API returned an empty or non-JSON response." };
  return { data: body };
}

/** React hook: { loading, data, error }. Re-fetches when `path` changes; ignores stale responses. */
export function useApi(path, retryKey = 0) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let live = true;
    setState({ loading: true });
    getJson(path).then((r) => live && setState({ loading: false, ...r }));
    return () => { live = false; };
  }, [path, retryKey]);
  return state;
}
