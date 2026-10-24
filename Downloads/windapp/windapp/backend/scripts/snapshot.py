"""Fetch Elexon data once and store it in backend/data/ (committed, so deploys don't depend on the live API).

Run:  python -m scripts.snapshot     (from the backend/ directory)
"""
import asyncio
import logging

from app.elexon import load_data

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    a, f = asyncio.run(load_data(force_refresh=True))
    print(f"actuals: {len(a)} rows, forecasts: {len(f)} rows")
