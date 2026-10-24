"""API contract tests with synthetic data (skipped if FastAPI/httpx are not installed)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from tests.test_analysis import _synthetic  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    f, a = _synthetic(days=31)

    async def fake_load(force_refresh=False):
        return a, f

    monkeypatch.setattr(main, "load_data", fake_load)
    return TestClient(main.app)


def test_health_and_config(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/config").json()["first_day"] == "2026-01-01"
    assert client.get("/config").status_code == 200


def test_decision_both_forms(client):
    a = client.get("/api/decision/2026-01-15?cutoff=09:00").json()
    b = client.get("/api/decision?day=2026-01-15").json()
    assert a["periods"] == 48 and a == b


def test_decision_validation(client):
    assert client.get("/api/decision/2025-12-31").status_code == 422
    assert client.get("/api/decision/2026-01-15?cutoff=abc").status_code == 422


def test_accuracy(client):
    j = client.get("/api/accuracy").json()
    assert j["overall"]["mae_mw"] == 50.0 and len(j["by_hour"]) == 24
