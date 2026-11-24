from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from scanner.api import create_app
from scanner.backtest import run_backtest
from scanner.config import Settings
from scanner.cycles import CycleDetector
from scanner.db import make_session_factory
from scanner.detector import VariationDetector
from scanner.models import Extreme, Notification, Observation, Token, utcnow

BASE = datetime(2025, 3, 1, tzinfo=timezone.utc)
MINT = "TestMint111111111111111111111111111111111111"


@pytest.fixture
def env(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db")
    factory, _ = make_session_factory(settings)
    app = create_app(factory, settings, collector=None)
    return TestClient(app), factory, settings


def seed_series(factory, mint=MINT, prices=(1.0, 0.9, 0.95, 1.3, 1.25, 1.2, 1.3), liq=100000.0):
    with factory() as s:
        s.add(Token(mint=mint, first_seen_at=BASE, threshold_usd=50000.0, status="tracked"))
        for i, p in enumerate(prices):
            s.add(Observation(mint=mint, ts=BASE + timedelta(minutes=i), price_usd=p, market_cap=100000.0, fdv=110000.0, liquidity_usd=liq, volume_24h=5000.0, price_change_m5=1.0, price_change_h1=-2.0, price_change_h24=10.0, source="dexscreener"))
        s.commit()
        VariationDetector(s, 35.0, 2, 5.0).process(mint)
        CycleDetector(s, 35.0).process(mint)
        s.commit()


def test_root_serves_ui(env):
    client, _, _ = env
    r = client.get("/")
    assert r.status_code == 200 and "Solana Memecoin Scanner" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/vendor/lightweight-charts.js").status_code == 200


def test_settings_put_get_reset(env):
    client, _, _ = env
    r = client.put("/settings", json={"mcap_threshold_usd": 75000, "up_threshold_pct": 40.0, "mcap_max_usd": None})
    assert r.status_code == 200
    assert r.json()["effective"]["mcap_threshold_usd"] == 75000
    assert r.json()["effective"]["up_threshold_pct"] == 40.0
    assert r.json()["last_modified"] is not None
    g = client.get("/settings").json()
    assert g["overrides"]["mcap_threshold_usd"] == 75000
    assert client.put("/settings", json={"inconnu": 1}).status_code == 422
    assert client.put("/settings", json={"confirmation_window": 0}).status_code == 422
    r2 = client.post("/settings/reset")
    assert r2.status_code == 200 and r2.json()["overrides"] == {}


def test_favorites_crud(env):
    client, _, _ = env
    assert client.post("/favorites/" + MINT).status_code == 200
    favs = client.get("/favorites").json()
    assert any(f["mint"] == MINT for f in favs)
    assert client.delete("/favorites/" + MINT).status_code == 200
    assert not any(f["mint"] == MINT for f in client.get("/favorites").json())
    assert client.delete("/favorites/" + MINT).status_code == 404


def test_notifications_endpoints(env):
    client, factory, _ = env
    with factory() as s:
        s.add(Notification(ts=utcnow(), type="new_cycle", mint=MINT, message="Cycle test", read=False))
        s.commit()
    data = client.get("/notifications").json()
    assert data["unread"] == 1 and len(data["items"]) == 1
    nid = data["items"][0]["id"]
    assert client.post(f"/notifications/{nid}/read").status_code == 200
    assert client.get("/notifications").json()["unread"] == 0
    assert client.post("/notifications/read-all").status_code == 200


def test_chart_and_phase_and_summary(env):
    client, factory, _ = env
    seed_series(factory)
    ch = client.get(f"/tokens/{MINT}/chart?tf=all").json()
    assert len(ch["candles"]) == 7
    ch5 = client.get(f"/tokens/{MINT}/chart?tf=5m").json()
    assert 1 <= len(ch5["candles"]) <= 2
    assert len(ch["extremes"]) >= 3
    assert len(ch["cycles"]) == 1
    ph = client.get(f"/tokens/{MINT}/phase").json()
    assert ph["phase"] in ("new_cycle", "up", "down", "consolidation")
    summ = client.get("/tokens/summary").json()
    assert summ["total"] == 1 and summ["rows"][0]["mint"] == MINT
    assert summ["rows"][0]["latest"]["price_change_h24"] == 10.0
    ov = client.get(f"/tokens/{MINT}/overview").json()
    assert ov["token"]["mint"] == MINT and ov["ath_atl"]["ath"] == max([1.0, 0.9, 0.95, 1.3, 1.25, 1.2, 1.3])
    glob = client.get("/stats/global").json()
    assert glob["tokens_tracked"] == 1 and glob["cycles_today"] >= 0


def test_backtest_no_lookahead_and_tp(env):
    client, factory, _ = env
    seed_series(factory)
    with factory() as s:
        result = run_backtest(s, mint=MINT, capital=100.0, take_profit_pct=30.0, stop_loss_pct=20.0, fees_pct=0.5, slippage_pct=1.0, store=True)
        s.commit()
    assert result["summary"]["total_trades"] >= 1
    trade = result["trades"][0]
    assert trade["status"] in ("take_profit", "stop_loss", "end_of_period")
    with factory() as s:
        low = s.scalars(__import__("sqlalchemy").select(Extreme).where(Extreme.mint == MINT, Extreme.kind == "low")).first()
        assert low is not None and low.confirmed_at is not None
        confirmed_utc = low.confirmed_at.replace(tzinfo=timezone.utc)
        assert trade["entry_ts"] >= confirmed_utc
    r = client.post("/backtest/run", json={"mint": MINT, "capital": 100, "take_profit_pct": 30, "stop_loss_pct": 20, "entry_mode": "low_confirmation"})
    assert r.status_code == 200 and r.json()["summary"]["total_trades"] >= 1
    assert r.json()["simulation_id"] is not None
    lst = client.get("/backtest/simulations?mint=" + MINT).json()
    assert len(lst) >= 1
    det = client.get(f"/backtest/simulations/{lst[0]['id']}").json()
    assert len(det["trades"]) >= 1
    cmp = client.post("/backtest/compare", json={"mint": MINT, "configs": [{"capital": 100, "take_profit_pct": 20, "stop_loss_pct": 20}, {"capital": 100, "take_profit_pct": 40, "stop_loss_pct": 20}]})
    assert cmp.status_code == 200 and len(cmp.json()["results"]) == 2
    assert client.post("/backtest/run", json={"mint": MINT, "entry_mode": "bidon"}).status_code == 422
