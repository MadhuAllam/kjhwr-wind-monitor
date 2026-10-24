from datetime import date, time

import pandas as pd

from app import analysis as an


def _ts(s):
    return pd.Timestamp(s, tz="UTC")


def test_cutoff_is_previous_day_london():
    # January = GMT, so 09:00 London == 09:00 UTC on D-1
    assert an.cutoff_utc(date(2026, 1, 10)) == _ts("2026-01-09 09:00")


def test_picks_latest_forecast_before_cutoff_and_ignores_later():
    f = pd.DataFrame(
        {
            "start": [_ts("2026-01-10 12:00")] * 3,
            "publish": [_ts("2026-01-09 03:00"), _ts("2026-01-09 08:00"), _ts("2026-01-09 10:00")],
            "forecast": [100.0, 200.0, 999.0],
        }
    )
    out = an.decision_forecast(f, date(2026, 1, 10))
    assert len(out) == 1 and out.forecast.iloc[0] == 200.0
    assert out.horizon_h.iloc[0] == 28.0


def test_metrics_and_sign_convention():
    f = pd.DataFrame(
        {
            "start": [_ts("2026-01-10 00:00"), _ts("2026-01-10 00:30")],
            "publish": [_ts("2026-01-09 06:00")] * 2,
            "forecast": [110.0, 80.0],
        }
    )
    a = pd.DataFrame({"start": f.start, "actual": [100.0, 100.0]})
    t = an.decision_table(f, a, date(2026, 1, 10), date(2026, 1, 10))
    m = an.metrics(t)
    assert m["mae_mw"] == 15.0
    assert m["bias_mw"] == -5.0  # (+10, -20)
    assert round(m["rmse_mw"], 3) == round(((100 + 400) / 2) ** 0.5, 3)
    assert m["wape_pct"] == 15.0


# ---- trailing margin / conservative wind -------------------------------------------------

def _synthetic(days=12, over=50.0):
    """Jan 1..days, forecast published 06:00 on D-1, actual = 1000, forecast = 1000 + over."""
    fr, ar = [], []
    for i in range(days):
        d = pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=i)
        for k in range(48):
            s = d + pd.Timedelta(minutes=30 * k)
            fr.append({"start": s, "publish": d - pd.Timedelta(hours=18), "forecast": 1000.0 + over})
            ar.append({"start": s, "actual": 1000.0})
    return pd.DataFrame(fr), pd.DataFrame(ar).drop_duplicates("start")


def test_trailing_window_ends_d_minus_2_and_needs_history():
    f, a = _synthetic()
    # Jan 2: window would end Dec 31 -> no history in scope
    assert an.trailing_margin(f, a, date(2026, 1, 2), time(9, 0), date(2026, 1, 1)) is None
    m = an.trailing_margin(f, a, date(2026, 1, 10), time(9, 0), date(2026, 1, 1))
    assert m["window_to"] == "2026-01-08" and m["window_from"] == "2026-01-02"
    assert m["p90_overforecast_mw"] == 50.0


def test_no_lookahead_in_trailing_window():
    f, a = _synthetic()
    a = a.copy()
    a.loc[a.start >= pd.Timestamp("2026-01-09", tz="UTC"), "actual"] = 0.0  # D-1 and D data must not leak
    m = an.trailing_margin(f, a, date(2026, 1, 10), time(9, 0), date(2026, 1, 1))
    assert m["p90_overforecast_mw"] == 50.0


def test_build_decision_conservative_and_floor():
    f, a = _synthetic(over=50.0)
    d = an.build_decision(f, a, date(2026, 1, 10), time(9, 0), date(2026, 1, 1))
    assert d["periods"] == 48 and d["margin_mw"] == 50.0
    assert d["series"][0]["conservative"] == 1000.0  # 1050 - 50
    assert d["procurement"]["expected_wind_mwh"] == 1050.0 * 24
    assert d["procurement"]["conservative_wind_mwh"] == 1000.0 * 24
    # forecast below margin floors at zero
    f2 = f.assign(forecast=10.0)
    f2.loc[:, "forecast"] = 10.0
    a2 = a.assign(actual=-100.0)  # forces large over-forecast margin (110)
    d2 = an.build_decision(f2, a2, date(2026, 1, 10), time(9, 0), date(2026, 1, 1))
    assert d2["series"][0]["conservative"] == 0.0


def test_early_days_have_no_margin_so_conservative_is_none():
    f, a = _synthetic()
    d = an.build_decision(f, a, date(2026, 1, 2), time(9, 0), date(2026, 1, 1))
    assert d["margin_mw"] is None and d["series"][0]["conservative"] is None


def test_under_forecast_gives_zero_overforecast_margin():
    f, a = _synthetic(over=-80.0)
    m = an.trailing_margin(f, a, date(2026, 1, 10), time(9, 0), date(2026, 1, 1))
    assert m["p90_overforecast_mw"] == 0.0 and m["bias_mw"] == -80.0


def test_mpe_and_overforecast_percentiles():
    f = pd.DataFrame({"start": [_ts("2026-01-10 00:00"), _ts("2026-01-10 00:30")],
                      "publish": [_ts("2026-01-09 06:00")] * 2, "forecast": [110.0, 90.0]})
    a = pd.DataFrame({"start": f.start, "actual": [100.0, 100.0]})
    m = an.metrics(an.decision_table(f, a, date(2026, 1, 10), date(2026, 1, 10)))
    assert m["mpe_pct"] == 0.0 and m["max_over_forecast_mw"] == 10.0 and m["max_under_forecast_mw"] == 10.0
