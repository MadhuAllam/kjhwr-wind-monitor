"""Decision-time forecast selection, accuracy metrics and the conservative-wind buffer.

A buyer trading in the GB day-ahead auction for delivery day D acts on D-1 before gate
closure. For every half hour of D we take the *latest WINDFOR forecast published at or
before that cutoff* (default 09:00 Europe/London on D-1) and compare it with the FUELHH
actual.

Sign convention: error = forecast - actual.
  error > 0  -> wind was OVER-forecast; the buyer would have bought too little thermal
                (the costly direction: the gap is covered at balancing-market prices).
  error < 0  -> wind was UNDER-forecast; the buyer over-bought.

Conservative wind = forecast - trailing P90 over-forecast margin, floored at 0. The margin is
estimated from delivery days D-8..D-2 only: at 09:00 on D-1 the actuals for D-1 are not yet
complete, so using them would be look-ahead.
"""
from __future__ import annotations

from datetime import date, time, timedelta

import numpy as np
import pandas as pd

LONDON = "Europe/London"
DEFAULT_CUTOFF = time(9, 0)
TRAILING_DAYS = 7
MIN_HISTORY_PERIODS = 48  # at least one day of scored half hours before we trust a margin


def cutoff_utc(delivery_day: date, cutoff: time = DEFAULT_CUTOFF) -> pd.Timestamp:
    local = pd.Timestamp.combine(delivery_day - timedelta(days=1), cutoff)
    return local.tz_localize(LONDON).tz_convert("UTC")


def day_bounds_utc(delivery_day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(delivery_day).tz_localize(LONDON).tz_convert("UTC")
    end = pd.Timestamp(delivery_day + timedelta(days=1)).tz_localize(LONDON).tz_convert("UTC")
    return start, end


def decision_forecast(forecasts: pd.DataFrame, delivery_day: date, cutoff: time = DEFAULT_CUTOFF) -> pd.DataFrame:
    """Latest forecast per target half hour known at the cutoff. Columns: start, publish, forecast, horizon_h."""
    c = cutoff_utc(delivery_day, cutoff)
    s, e = day_bounds_utc(delivery_day)
    f = forecasts[(forecasts.publish <= c) & (forecasts.start >= s) & (forecasts.start < e)]
    if f.empty:
        return f.assign(horizon_h=pd.Series(dtype=float))
    f = f.sort_values("publish").groupby("start", as_index=False).last()
    f["horizon_h"] = (f.start - f.publish).dt.total_seconds() / 3600
    return f


def decision_table(forecasts, actuals, first: date, last: date, cutoff: time = DEFAULT_CUTOFF) -> pd.DataFrame:
    frames = []
    for d in pd.date_range(first, last).date:
        f = decision_forecast(forecasts, d, cutoff)
        if not f.empty:
            frames.append(f.assign(delivery_day=d))
    cols = ["start", "publish", "forecast", "horizon_h", "delivery_day", "actual", "error"]
    if not frames:
        return pd.DataFrame(columns=cols)
    t = pd.concat(frames, ignore_index=True).merge(actuals, on="start", how="left")
    t["error"] = t.forecast - t.actual
    return t


def metrics(t: pd.DataFrame) -> dict:
    v = t.dropna(subset=["actual"])
    if v.empty:
        return {"n": 0}
    e, a = v.error.to_numpy(dtype=float), v.actual.to_numpy(dtype=float)
    ae = np.abs(e)
    nz = a > 0
    return {
        "n": int(len(v)),
        "mae_mw": float(ae.mean()),
        "rmse_mw": float(np.sqrt((e**2).mean())),
        "bias_mw": float(e.mean()),
        "mpe_pct": float((e[nz] / a[nz]).mean() * 100) if nz.any() else None,
        "mape_pct": float((ae[nz] / a[nz]).mean() * 100) if nz.any() else None,
        "wape_pct": float(ae.sum() / a.sum() * 100) if a.sum() else None,
        "p50_abs_error_mw": float(np.percentile(ae, 50)),
        "p90_abs_error_mw": float(np.percentile(ae, 90)),
        "p95_abs_error_mw": float(np.percentile(ae, 95)),
        "p90_overforecast_mw": float(max(np.percentile(e, 90), 0.0)),
        "p95_overforecast_mw": float(max(np.percentile(e, 95), 0.0)),
        "max_over_forecast_mw": float(max(e.max(), 0.0)),
        "max_under_forecast_mw": float(max(-e.min(), 0.0)),
        "mean_actual_mw": float(a.mean()),
    }


def by_day(t: pd.DataFrame) -> list[dict]:
    out = []
    for d, g in t.groupby("delivery_day"):
        m = metrics(g)
        if m["n"]:
            out.append({"delivery_day": str(d), **m})
    return out


def by_hour(t: pd.DataFrame) -> list[dict]:
    v = t.dropna(subset=["actual"]).copy()
    v["hour"] = v.start.dt.tz_convert(LONDON).dt.hour
    out = []
    for h, g in v.groupby("hour"):
        e = g.error.to_numpy(dtype=float)
        out.append(
            {
                "hour": int(h),
                "mae_mw": float(np.abs(e).mean()),
                "rmse_mw": float(np.sqrt((e**2).mean())),
                "bias_mw": float(e.mean()),
                "p90_abs_error_mw": float(np.percentile(np.abs(e), 90)),
                "n": int(len(g)),
            }
        )
    return out


def by_horizon(forecasts, actuals, first: date, last: date, bucket_h: int = 6) -> list[dict]:
    """MAE vs forecast lead time using every forecast issued (not only decision-time ones)."""
    s, _ = day_bounds_utc(first)
    _, e = day_bounds_utc(last)
    f = forecasts[(forecasts.start >= s) & (forecasts.start < e)].merge(actuals, on="start")
    f["horizon_h"] = (f.start - f.publish).dt.total_seconds() / 3600
    f = f[f.horizon_h >= 0].copy()
    if f.empty:
        return []
    f["err"] = (f.forecast - f.actual).abs()
    f["bucket"] = (f.horizon_h // bucket_h * bucket_h).astype(int)
    return [
        {"horizon_from_h": int(b), "horizon_to_h": int(b + bucket_h), "mae_mw": float(g.err.mean()), "n": int(len(g))}
        for b, g in f.groupby("bucket")
    ]


def error_histogram(t: pd.DataFrame, bins: int = 30) -> list[dict]:
    e = t.dropna(subset=["error"]).error.to_numpy(dtype=float)
    if not len(e):
        return []
    counts, edges = np.histogram(e, bins=bins)
    return [{"from_mw": float(edges[i]), "to_mw": float(edges[i + 1]), "count": int(counts[i])} for i in range(bins)]


def trailing_margin(forecasts, actuals, delivery_day: date, cutoff: time, scope_first: date, window: int = TRAILING_DAYS):
    """Error statistics from the `window` days ending D-2 (what the trader can know at the cutoff)."""
    last_known = delivery_day - timedelta(days=2)
    first = max(scope_first, last_known - timedelta(days=window - 1))
    if last_known < first:
        return None
    hist = decision_table(forecasts, actuals, first, last_known, cutoff)
    m = metrics(hist)
    if m["n"] < MIN_HISTORY_PERIODS:
        return None
    return {"window_from": str(first), "window_to": str(last_known), **m}


def series(t: pd.DataFrame, margin_mw: float | None) -> list[dict]:
    out = []
    for r in t.itertuples():
        cons = None if margin_mw is None else float(max(r.forecast - margin_mw, 0.0))
        out.append(
            {
                "start": r.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "publish": r.publish.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "forecast": float(r.forecast),
                "conservative": cons,
                "actual": None if pd.isna(r.actual) else float(r.actual),
                "error": None if pd.isna(r.error) else float(r.error),
            }
        )
    return out


def build_decision(forecasts, actuals, delivery_day: date, cutoff: time, scope_first: date) -> dict:
    """Everything the Decision view needs. Raises LookupError if no forecast existed at the cutoff."""
    t = decision_table(forecasts, actuals, delivery_day, delivery_day, cutoff)
    if t.empty:
        raise LookupError("no forecast was available at that cutoff")
    hist = trailing_margin(forecasts, actuals, delivery_day, cutoff, scope_first)
    margin = hist["p90_overforecast_mw"] if hist else None
    fc = t.forecast.to_numpy(dtype=float)
    expected = float(fc.sum() * 0.5)  # MW x 0.5 h
    conservative = float(np.clip(fc - margin, 0, None).sum() * 0.5) if margin is not None else None
    return {
        "delivery_day": str(delivery_day),
        "cutoff_london": cutoff.strftime("%H:%M"),
        "cutoff_utc": cutoff_utc(delivery_day, cutoff).isoformat(),
        "latest_publish_time": t.publish.max().isoformat(),
        "earliest_publish_time": t.publish.min().isoformat(),
        "periods": int(len(t)),
        "series": series(t, margin),
        "outcome_metrics": metrics(t),  # hindsight: scored against the day's actuals
        "trailing_metrics": hist,       # known at decision time (D-8..D-2)
        "margin_mw": margin,
        "procurement": {
            "expected_wind_mwh": expected,
            "conservative_wind_mwh": conservative,
            "extra_thermal_cover_mwh": None if conservative is None else expected - conservative,
        },
    }
