# Day-Ahead Wind Forecast Desk

A decision-support web app for a GB utility's day-ahead power-buying desk. It answers two questions:

1. **What is the latest wind forecast I could actually have used when I had to trade?**
2. **How wrong have those forecasts been, in MW, so I can size my cover accordingly?**

Scope: national GB wind only, Elexon BMRS only (`FUELHH` actuals with `fuelType = WIND`, `WINDFOR` forecasts),
for **delivery days in January 2026**.

**Live app:** `https://windapp-zqwf.vercel.app/`

> ## AI-assistance disclosure
> This project was built with the assistance of AI tools (Claude, by Anthropic) for design, code generation,
> test writing and documentation. All code was reviewed, run and is understood by the submitter.

---

## 1. Architecture

```
 Elexon BMRS API  ──►  scripts/snapshot.py  ──►  backend/data/*.json   (one-off, committed)
 (FUELHH, WINDFOR)                                      │
                                                        ▼
 React + Vite UI  ◄──── JSON /api/* ────  FastAPI  ──  analysis.py  (pandas, pure functions)
 (Recharts)                                  │
                                             └── serves the built UI at "/" in Docker
```

- **Data Sources:** 
  - Actuals: [Elexon FUELHH Stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream) (`fuelType = WIND`, 30-min settlement)
  - Forecasts: [Elexon WINDFOR Stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream) (`publishTime`, `startTime`, `generation`)

  
* **Snapshot, not live calls.** Data is fetched once into two JSON files. The app is fast, reproducible and
  independent of Elexon availability (important for serverless deploys). `POST /api/refresh` re-pulls it.
* **Analysis is pure and tested.** `analysis.py` has no web or network code, so every number on screen is unit-tested.
* **One origin in production.** The Docker image serves the UI and API together, so no CORS/proxy issues.

### Directory structure

| Path | Purpose |
|---|---|
| `backend/app/elexon.py` | Elexon client (retries, chunked WINDFOR fetch), snapshot load/save. Data path is resolved from the file location, never the working directory (override: `DATA_DIR`). |
| `backend/app/analysis.py` | Cutoff logic, decision-time forecast selection, metrics, trailing margin, conservative wind |
| `backend/app/main.py` | FastAPI routes, CORS (`*`), JSON error handler, startup preload, static UI mount |
| `backend/run.py` | Local launcher: binds `127.0.0.1:8000`, fails clearly if the port is taken |
| `backend/scripts/snapshot.py` | Downloads January 2026 data into `backend/data/` |
| `backend/tests/` | `test_analysis.py` (logic, no-look-ahead), `test_api.py` (endpoint contract) |
| `backend/data/` | `actuals.json`, `forecasts.json` (the snapshot) |
| `frontend/src/api.js` | Fetch helper that never throws on empty/non-JSON bodies; `useApi` hook |
| `frontend/src/views.jsx` | Decision view and Forecast accuracy view |
| `frontend/vite.config.js` | Dev proxy for `/api` and `/config` → `http://127.0.0.1:8000` |
| `Dockerfile`, `docker-compose.yml`, `heroku.yml` | Container build / run / Heroku container deploy |
| `vercel.json`, `api/index.py`, `requirements.txt` | Vercel deploy (static UI + Python function) |

### API

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Status, whether snapshot files exist and loaded, row counts |
| `GET /api/config` (alias `/config`) | Valid delivery-day range, default cutoff |
| `GET /api/decision/{YYYY-MM-DD}?cutoff=09:00` (or `/api/decision?day=…`) | Selected forecast, conservative wind, actuals, KPIs for one delivery day |
| `GET /api/accuracy?cutoff=09:00` | January metrics, by-day, by-hour, by-lead-time, error histogram |
| `POST /api/refresh` | Re-download the snapshot |

---

## 2. Run it

Prerequisites for a native run: Python 3.11+, Node 20+. The snapshot (`backend/data/actuals.json`,
`forecasts.json`) must exist; to create it: `cd backend && python -m scripts.snapshot`.

### Native (two terminals)

```bash
# Terminal 1 – API on http://127.0.0.1:8000
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
curl http://127.0.0.1:8000/api/health                  # sanity check

# Terminal 2 – UI on http://localhost:5173
cd frontend
npm install
npm run dev
```

### Docker Compose

```bash
docker compose up --build      # then open http://127.0.0.1:8000
```

### Tests

```bash
cd backend && python -m pytest
```

### Deploy

* **Vercel:** commit `backend/data/*.json`, push to GitHub, import the repo in Vercel (no settings needed;
  `vercel.json` is picked up). The static UI is built from `frontend/`, and `api/index.py` exposes the FastAPI app.
* **Heroku:** `heroku stack:set container && git push heroku main` (uses `heroku.yml` + `Dockerfile`).

---

## 3. Day-ahead cutoff logic

Power for delivery day **D** is bought in the day-ahead auction on **D-1**. The default cutoff is **09:00 London time on D-1**
(editable in the UI; set it to your desk's actual gate closure).

For every half-hour settlement period of D the app picks the **latest WINDFOR forecast whose `publishTime` ≤ cutoff**.
Forecasts published after the cutoff are ignored, so the evaluation contains no look-ahead. That selected forecast is
what is compared with the FUELHH actual.

Sign convention: **error = forecast − actual**. Positive = wind over-forecast → too little thermal bought → the gap is
covered at balancing prices (the costly direction).

## 4. Error metrics

| Metric | Meaning |
|---|---|
| MAE | mean \|error\| (MW) |
| RMSE | root mean squared error (MW); penalises large misses |
| Mean bias / MPE | mean error (MW) / mean error as % of actual; sign shows systematic over- or under-forecasting |
| WAPE | Σ\|error\| / Σactual |
| P90 / P95 absolute error | 90th/95th percentile of \|error\| – "how bad is a bad period" |
| P90 over-forecast | 90th percentile of signed error, floored at 0 – the downside margin that matters to a buyer |

**Conservative wind** = max(selected forecast − trailing P90 over-forecast, 0). The margin is estimated from the 7 delivery
days ending **D-2**, because at 09:00 on D-1 the actuals for D-1 are not yet complete (using them would be look-ahead).
For the first days of January there is no scored history in scope, so no margin is shown rather than inventing one.
"Extra thermal cover" is expected wind minus conservative wind (MWh), the extra volume a risk-averse desk might add.

Assumptions: the margin is applied as a flat MW haircut per half hour (simple and transparent, not a probabilistic model);
the 09:00 default is an approximation of gate closure; national-level figures only.

---

## 5. 10-minute presentation guide

### Part 1 (0:00–5:00) – Client pitch: trader decision-making and risk

| Time | Show | Say |
|---|---|---|
| 0:00–0:45 | Title / Decision view | "Every morning you commit to day-ahead volumes using a wind forecast. Wind is your biggest swing factor and the forecast is never perfect. This desk shows what you could know, and how much to trust it." |
| 0:45–2:00 | Pick a windy January day. Point at the banner | "We reproduce your exact decision moment: 09:00 on D-1. We use only forecasts published by then; later ones are ignored, so there is no hindsight flattery." |
| 2:00–3:15 | Chart: forecast vs conservative vs actual | "Blue is the forecast you had; green is the same forecast with a buffer from the last week's misses; orange is what really happened. The cover figure tells you how many extra MWh of thermal protect you." |
| 3:15–4:30 | Accuracy tab: MAE, RMSE, bias, P90 | "Across January the forecast missed by X MW on average, but bad periods reach Y MW. Bias says whether it errs high or low." (read the real numbers) |
| 4:30–5:00 | Hour-of-day chart, close | "Errors cluster at certain hours, so cover can be targeted. Next: add solar, live data, prices, and per-hour buffers." |

### Part 2 (5:00–10:00) – Technical lead review

| Time | Show | Say |
|---|---|---|
| 5:00–6:00 | Architecture diagram (section 1) | "Snapshot → pure analysis → thin FastAPI → React. One container in production." |
| 6:00–7:15 | `elexon.py` | "Chunked WINDFOR fetch by publish time, retries with backoff, dedupe on (startTime, publishTime). Data path is file-relative." |
| 7:15–8:30 | `analysis.py`: `decision_forecast`, `trailing_margin` | "Core logic: ≤ cutoff, latest per period, DST-safe London→UTC conversion. Margin window ends D-2 to avoid look-ahead." |
| 8:30–9:15 | Run `python -m pytest` | "Tests cover cutoff conversion, ignoring later forecasts, metric maths, no-look-ahead (poisoning future actuals changes nothing), conservative floor at 0, and the API contract." |
| 9:15–10:00 | `main.py`, `api.js`, Dockerfile, vercel.json | "JSON error handler so the UI never sees an empty body, defensive fetch helper, IPv4 proxy target, multi-stage Docker, Vercel deploy. Limitations: single-cutoff assumption, flat haircut, no live feed." |

Tips: record at 1080p, open every submitted URL in an incognito window before sending, and keep the video ≤ 10:00.
