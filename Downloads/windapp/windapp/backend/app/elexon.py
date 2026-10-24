"""Elexon BMRS client + local snapshot cache.

Actuals  : FUELHH stream, fuelType=WIND   (startTime, generation)
Forecasts: WINDFOR stream                 (startTime, publishTime, generation)

Scope: purchase decisions for delivery days in January 2026. Forecasts are
therefore fetched by *publish time* from 2025-12-25 to 2026-01-31, which
covers everything that could have informed a decision for any January day.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pandas as pd

log = logging.getLogger(__name__)

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
# Always resolved from this file, never from the working directory (override with DATA_DIR).
DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).resolve().parent.parent / "data").resolve()
ACTUALS_FILE = DATA_DIR / "actuals.json"
FORECASTS_FILE = DATA_DIR / "forecasts.json"

SCOPE_FIRST_DELIVERY = date(2026, 1, 1)
SCOPE_LAST_DELIVERY = date(2026, 1, 31)
FORECAST_PUBLISH_FROM = datetime(2025, 12, 25, tzinfo=timezone.utc)
FORECAST_PUBLISH_TO = datetime(2026, 2, 1, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(payload):
    """Stream endpoints return a bare array; non-stream ones wrap in {'data': []}."""
    if isinstance(payload, dict):
        return payload.get("data", [])
    return payload


async def _get(client: httpx.AsyncClient, path: str, params: dict, retries: int = 4):
    for attempt in range(retries):
        try:
            r = await client.get(f"{BASE_URL}{path}", params=params, timeout=60)
            r.raise_for_status()
            return _rows(r.json())
        except (httpx.HTTPError, ValueError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2**attempt
            log.warning("Elexon request failed (%s); retrying in %ss", exc, wait)
            await asyncio.sleep(wait)


async def fetch_actuals() -> list[dict]:
    """Actual wind generation for all of January 2026 (30 min resolution)."""
    async with httpx.AsyncClient() as client:
        rows = await _get(
            client,
            "/datasets/FUELHH/stream",
            {
                "settlementDateFrom": SCOPE_FIRST_DELIVERY.isoformat(),
                "settlementDateTo": SCOPE_LAST_DELIVERY.isoformat(),
                "fuelType": "WIND",
            },
        )
    return [
        {"startTime": r["startTime"], "generation": r["generation"]}
        for r in rows
        if r.get("fuelType", "WIND") == "WIND"
    ]


async def fetch_forecasts(chunk_days: int = 2, concurrency: int = 4) -> list[dict]:
    """All WINDFOR forecasts published between 25 Dec 2025 and 31 Jan 2026."""
    windows, t = [], FORECAST_PUBLISH_FROM
    while t < FORECAST_PUBLISH_TO:
        nxt = min(t + timedelta(days=chunk_days), FORECAST_PUBLISH_TO)
        windows.append((t, nxt))
        t = nxt
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient() as client:

        async def one(w):
            async with sem:
                return await _get(
                    client,
                    "/datasets/WINDFOR/stream",
                    {"publishDateTimeFrom": _iso(w[0]), "publishDateTimeTo": _iso(w[1])},
                )

        chunks = await asyncio.gather(*(one(w) for w in windows))

    seen, out = set(), []
    for rows in chunks:
        for r in rows:
            key = (r["startTime"], r["publishTime"])
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "startTime": r["startTime"],
                    "publishTime": r["publishTime"],
                    "generation": r["generation"],
                }
            )
    return out


def _to_actuals_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["startTime", "generation"])
    df["start"] = pd.to_datetime(df["startTime"], utc=True)
    df = df.rename(columns={"generation": "actual"})[["start", "actual"]]
    return df.drop_duplicates("start").sort_values("start").reset_index(drop=True)


def _to_forecasts_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["startTime", "publishTime", "generation"])
    df["start"] = pd.to_datetime(df["startTime"], utc=True)
    df["publish"] = pd.to_datetime(df["publishTime"], utc=True)
    df = df.rename(columns={"generation": "forecast"})[["start", "publish", "forecast"]]
    return df.drop_duplicates(["start", "publish"]).reset_index(drop=True)


_cache: dict[str, pd.DataFrame] = {}
_lock = asyncio.Lock()


async def load_data(force_refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (actuals, forecasts). Order: memory -> snapshot file -> live API."""
    async with _lock:
        if not force_refresh and "a" in _cache:
            return _cache["a"], _cache["f"]
        if not force_refresh and ACTUALS_FILE.exists() and FORECASTS_FILE.exists():
            a_rows = json.loads(ACTUALS_FILE.read_text())
            f_rows = json.loads(FORECASTS_FILE.read_text())
            log.info("Loaded snapshot from %s", DATA_DIR)
        else:
            a_rows, f_rows = await asyncio.gather(fetch_actuals(), fetch_forecasts())
            try:  # read-only filesystems (e.g. serverless) are fine to skip
                DATA_DIR.mkdir(exist_ok=True)
                ACTUALS_FILE.write_text(json.dumps(a_rows))
                FORECASTS_FILE.write_text(json.dumps(f_rows))
            except OSError:
                pass
        _cache["a"], _cache["f"] = _to_actuals_df(a_rows), _to_forecasts_df(f_rows)
        return _cache["a"], _cache["f"]
