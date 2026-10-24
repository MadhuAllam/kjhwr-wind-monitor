import React, { useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ReferenceLine,
} from "recharts";
import { useApi } from "./api.js";

const fmt = (x, d = 0) => (x == null || Number.isNaN(x) ? "–" : Number(x).toLocaleString("en-GB", { maximumFractionDigits: d }));
const tz = { timeZone: "Europe/London" };
const hhmm = (iso) => new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...tz });
const stamp = (iso) => new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", ...tz });

const Kpi = ({ label, value, unit, note }) => (
  <div className="card kpi">
    <h3>{label}</h3>
    <span className="v">{value}</span> <span className="u">{unit}</span>
    {note && <div className="n">{note}</div>}
  </div>
);

const Status = ({ loading, error }) => (
  <>
    {loading && <p>Loading…</p>}
    {error && <div className="banner warn"><b>Error:</b> {error}</div>}
  </>
);

export function DecisionView({ cfg, cutoff }) {
  const [day, setDay] = useState(cfg.first_day);
  const { data, error, loading } = useApi(`/api/decision/${day}?cutoff=${encodeURIComponent(cutoff)}`);
  const rows = (data?.series ?? []).map((r) => ({ ...r, t: hhmm(r.start) }));
  const p = data?.procurement, tm = data?.trailing_metrics, om = data?.outcome_metrics;
  const hasCons = rows.some((r) => r.conservative != null);

  return (
    <>
      <div className="controls">
        <label>
          Delivery day (January 2026)
          <input type="date" min={cfg.first_day} max={cfg.last_day} value={day}
                 onChange={(e) => e.target.value && setDay(e.target.value)} />
        </label>
        <button onClick={() => setDay(shift(day, -1, cfg))}>◀ Prev</button>
        <button onClick={() => setDay(shift(day, 1, cfg))}>Next ▶</button>
      </div>
      <Status loading={loading} error={error} />
      {data && (
        <>
          <div className="banner">
            Decision taken on <b>{shiftLabel(day)}</b> at <b>{data.cutoff_london}</b> London. For each half hour the latest forecast
            published on or before then is used; the newest of these was issued <b>{stamp(data.latest_publish_time)}</b>.
            Anything published later is ignored.
          </div>
          <div className="grid">
            <Kpi label="Forecast wind, delivery day" value={fmt(p?.expected_wind_mwh)} unit="MWh" />
            <Kpi label="Conservative wind" value={fmt(p?.conservative_wind_mwh)} unit="MWh"
                 note={data.margin_mw != null ? `forecast − ${fmt(data.margin_mw)} MW (trailing P90 over-forecast)` : "needs ≥1 scored day before D-1; none in scope yet"} />
            <Kpi label="Extra thermal cover suggested" value={fmt(p?.extra_thermal_cover_mwh)} unit="MWh" note="expected − conservative wind" />
            <Kpi label="Trailing error (MAE)" value={fmt(tm?.mae_mw)} unit="MW"
                 note={tm ? `${tm.window_from} → ${tm.window_to}, bias ${fmt(tm.bias_mw)} MW` : "no history available"} />
            <Kpi label="Outcome (hindsight): MAE" value={fmt(om?.mae_mw)} unit="MW"
                 note={om?.n ? `${om.n} periods scored vs actuals` : "no actuals"} />
          </div>
          <div className="card">
            <h3>Selected forecast vs actual vs conservative wind (MW, London time)</h3>
            <ResponsiveContainer width="100%" height={340}>
              <LineChart data={rows}>
                <CartesianGrid stroke="#e3e7ec" />
                <XAxis dataKey="t" interval={5} />
                <YAxis />
                <Tooltip formatter={(v) => (v == null ? "–" : `${fmt(v)} MW`)} />
                <Legend />
                <Line dataKey="forecast" name="Selected forecast" stroke="#1f6feb" dot={false} strokeWidth={2} />
                {hasCons && <Line dataKey="conservative" name="Conservative wind" stroke="#0a7f5a" dot={false} strokeWidth={2} strokeDasharray="6 4" />}
                <Line dataKey="actual" name="Actual wind" stroke="#e8590c" dot={false} strokeWidth={2} connectNulls={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </>
  );
}

function shift(day, n, cfg) {
  const d = new Date(day + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  const s = d.toISOString().slice(0, 10);
  return s < cfg.first_day || s > cfg.last_day ? day : s;
}
function shiftLabel(day) {
  const d = new Date(day + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

const Chart = ({ title, children, wide }) => (
  <div className="card" style={wide ? { gridColumn: "1 / -1" } : undefined}>
    <h3>{title}</h3>
    <ResponsiveContainer width="100%" height={260}>{children}</ResponsiveContainer>
  </div>
);

export function AccuracyView({ cutoff }) {
  const { data, error, loading } = useApi(`/api/accuracy?cutoff=${encodeURIComponent(cutoff)}`);
  if (loading || error) return <Status loading={loading} error={error} />;
  const o = data.overall;
  if (!o.n) return <div className="banner warn">No scored periods for this cutoff.</div>;
  const grid = <CartesianGrid stroke="#e3e7ec" />;
  return (
    <>
      <div className="banner">
        Decision-time forecast (cutoff {data.cutoff_london} on D-1) scored against actuals for all January 2026 delivery days
        ({fmt(o.n)} half hours). Error = forecast − actual: positive means wind was <b>over-forecast</b> (too little thermal bought).
      </div>
      <div className="grid">
        <Kpi label="MAE" value={fmt(o.mae_mw)} unit="MW" note={`${fmt(o.wape_pct, 1)}% of generation (WAPE)`} />
        <Kpi label="RMSE" value={fmt(o.rmse_mw)} unit="MW" />
        <Kpi label="Mean bias" value={fmt(o.bias_mw)} unit="MW" note={`MPE ${fmt(o.mpe_pct, 1)}% · ${o.bias_mw > 0 ? "over-forecasts" : "under-forecasts"} on average`} />
        <Kpi label="P90 absolute error" value={fmt(o.p90_abs_error_mw)} unit="MW" note={`P95 ${fmt(o.p95_abs_error_mw)} MW`} />
        <Kpi label="P90 over-forecast" value={fmt(o.p90_overforecast_mw)} unit="MW" note="the downside that drives thermal cover" />
        <Kpi label="Worst over / under" value={`${fmt(o.max_over_forecast_mw)} / ${fmt(o.max_under_forecast_mw)}`} unit="MW" />
      </div>
      <div className="two">
        <Chart title="MAE by hour of day (MW, London)">
          <BarChart data={data.by_hour}>{grid}<XAxis dataKey="hour" /><YAxis /><Tooltip /><Legend />
            <Bar dataKey="mae_mw" name="MAE" fill="#1f6feb" /><Bar dataKey="p90_abs_error_mw" name="P90 abs error" fill="#9db8e8" /></BarChart>
        </Chart>
        <Chart title="Bias by hour of day (MW, + = over-forecast)">
          <BarChart data={data.by_hour}>{grid}<XAxis dataKey="hour" /><YAxis /><Tooltip /><ReferenceLine y={0} stroke="#444" />
            <Bar dataKey="bias_mw" name="Bias" fill="#7c3aed" /></BarChart>
        </Chart>
        <Chart title="MAE by delivery day (MW)">
          <BarChart data={data.by_day}>{grid}<XAxis dataKey="delivery_day" tickFormatter={(d) => d.slice(8)} /><YAxis /><Tooltip />
            <Bar dataKey="mae_mw" name="MAE" fill="#e8590c" /></BarChart>
        </Chart>
        <Chart title="MAE vs forecast lead time (all forecasts issued)">
          <BarChart data={data.by_horizon.map((h) => ({ ...h, label: `${h.horizon_from_h}-${h.horizon_to_h}h` }))}>{grid}
            <XAxis dataKey="label" /><YAxis /><Tooltip /><Bar dataKey="mae_mw" name="MAE" fill="#0a7f5a" /></BarChart>
        </Chart>
        <Chart wide title="Error distribution (MW, forecast − actual)">
          <BarChart data={data.error_histogram.map((b) => ({ ...b, label: fmt((b.from_mw + b.to_mw) / 2) }))}>{grid}
            <XAxis dataKey="label" /><YAxis /><Tooltip /><Bar dataKey="count" name="Half hours" fill="#7c3aed" /></BarChart>
        </Chart>
      </div>
    </>
  );
}
