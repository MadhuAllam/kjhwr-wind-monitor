"""FastAPI app: JSON API under /api (plus /config alias) and, when built, the React UI at /."""
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import analysis as an
from .elexon import ACTUALS_FILE, FORECASTS_FILE, SCOPE_FIRST_DELIVERY, SCOPE_LAST_DELIVERY, load_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("windapp")

_status = {"loaded": False, "error": None, "actual_rows": 0, "forecast_rows": 0}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Preload the snapshot; a data problem must never stop the server from starting."""
    log.info("actuals=%s exists=%s | forecasts=%s exists=%s",
             ACTUALS_FILE, ACTUALS_FILE.exists(), FORECASTS_FILE, FORECASTS_FILE.exists())
    try:
        a, f = await load_data()
        _status.update(loaded=True, error=None, actual_rows=len(a), forecast_rows=len(f))
        log.info("Data ready: %d actual rows, %d forecast rows", len(a), len(f))
    except Exception as exc:  # noqa: BLE001
        _status.update(loaded=False, error=repr(exc))
        log.exception("Preload failed; will retry on first data request")
    yield


app = FastAPI(title="Day-Ahead Wind Forecast Desk", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


def _cutoff(c: str) -> time:
    try:
        return time.fromisoformat(c)
    except ValueError:
        raise HTTPException(422, "cutoff must be HH:MM (Europe/London, on the day before delivery)")


def _day(d: date) -> date:
    if not SCOPE_FIRST_DELIVERY <= d <= SCOPE_LAST_DELIVERY:
        raise HTTPException(422, "delivery day must be in January 2026")
    return d


async def _data():
    try:
        return await load_data()
    except Exception as exc:  # noqa: BLE001
        log.exception("Could not load data")
        raise HTTPException(503, f"Data unavailable ({exc}). Run `python -m scripts.snapshot` in backend/.")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "data": _status,
        "files": {"actuals": ACTUALS_FILE.exists(), "forecasts": FORECASTS_FILE.exists()},
    }


@app.get("/api/config")
@app.get("/config")  # alias so a proxy rule for /config also works
def config():
    return {
        "first_day": SCOPE_FIRST_DELIVERY.isoformat(),
        "last_day": SCOPE_LAST_DELIVERY.isoformat(),
        "default_cutoff": "09:00",
        "trailing_days": an.TRAILING_DAYS,
    }


@app.post("/api/refresh")
async def refresh():
    a, f = await load_data(force_refresh=True)
    _status.update(loaded=True, error=None, actual_rows=len(a), forecast_rows=len(f))
    return {"actual_rows": len(a), "forecast_rows": len(f)}


async def _decision(delivery_day: date, cutoff: str):
    d, c = _day(delivery_day), _cutoff(cutoff)
    a, f = await _data()
    try:
        return an.build_decision(f, a, d, c, SCOPE_FIRST_DELIVERY)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/decision")
async def decision_query(day: date = Query(..., description="Delivery day, YYYY-MM-DD"), cutoff: str = "09:00"):
    return await _decision(day, cutoff)


@app.get("/api/decision/{delivery_day}")
async def decision_path(delivery_day: date, cutoff: str = "09:00"):
    return await _decision(delivery_day, cutoff)


@app.get("/api/accuracy")
async def accuracy(cutoff: str = "09:00"):
    c = _cutoff(cutoff)
    a, f = await _data()
    t = an.decision_table(f, a, SCOPE_FIRST_DELIVERY, SCOPE_LAST_DELIVERY, c)
    return {
        "cutoff_london": c.strftime("%H:%M"),
        "overall": an.metrics(t),
        "by_day": an.by_day(t),
        "by_hour": an.by_hour(t),
        "by_horizon": an.by_horizon(f, a, SCOPE_FIRST_DELIVERY, SCOPE_LAST_DELIVERY),
        "error_histogram": an.error_histogram(t),
    }


# Serve the built React app when present (Docker image). Mounted last so /api routes win.
_static = Path(os.environ.get("STATIC_DIR") or Path(__file__).resolve().parent.parent / "static")
if _static.exists():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
