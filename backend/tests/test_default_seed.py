"""Opening the app for the first time shows the README's given data (sample_data/readme_given)."""
import time

from fastapi.testclient import TestClient

from sot.api.app import create_app


def _wait_run(c):
    for _ in range(100):
        runs = c.get("/api/runs").json()
        if runs and runs[0]["status"] != "running":
            return runs[0]
        time.sleep(0.1)
    raise AssertionError("seed run did not finish")


def test_first_start_seeds_the_given_data(settings, monkeypatch):
    monkeypatch.setenv("SOT_SEED", "1")
    with TestClient(create_app(settings)) as c:
        assert _wait_run(c)["status"] == "completed"
        s = c.get("/api/summary").json()
        assert s["files"] == 4 and s["persons"] == 2


def test_no_seed_when_data_exists_or_disabled(settings, monkeypatch):
    with TestClient(create_app(settings)) as c:  # SOT_SEED=0 from conftest
        time.sleep(0.3)
        assert c.get("/api/summary").json()["files"] == 0
    monkeypatch.setenv("SOT_SEED", "1")
    with TestClient(create_app(settings)) as c:
        _wait_run(c)
    with TestClient(create_app(settings)) as c:  # restart: data exists -> no second seed run
        time.sleep(0.3)
        assert len(c.get("/api/runs").json()) == 1
