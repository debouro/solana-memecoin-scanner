from datetime import datetime, timedelta, timezone

import pytest

from scanner.cycles import CycleDetector
from scanner.detector import VariationDetector
from scanner.models import Cycle, Extreme, Movement, Observation, Token

BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def setup_series(s, mint, prices, liq=100000.0):
    s.add(Token(mint=mint, first_seen_at=BASE, threshold_usd=50000.0, status="tracked"))
    for i, p in enumerate(prices):
        s.add(Observation(mint=mint, ts=BASE + timedelta(minutes=i), price_usd=p, market_cap=100000.0, fdv=110000.0, liquidity_usd=liq, volume_24h=1000.0, source="dexscreener"))
    s.commit()


def test_up_move_35_counted_once_and_cycle_detected(session_factory):
    prices = [1.0, 0.9, 0.95, 1.3, 1.25, 1.2, 1.3]
    with session_factory() as s:
        setup_series(s, "m1", prices)
        det = VariationDetector(s, 35.0, 2, 5.0)
        det.process("m1")
        det.process("m1")
        s.commit()
        movements = s.query(Movement).all()
        counted = [m for m in movements if m.counted]
        assert len(counted) == 1
        assert counted[0].type == "up"
        assert counted[0].amplitude_pct == pytest.approx((1.3 / 0.9 - 1) * 100, rel=1e-6)
        cyc = CycleDetector(s, 35.0)
        cyc.process("m1")
        cyc.process("m1")
        s.commit()
        cycles = s.query(Cycle).all()
        assert len(cycles) == 1
        c = cycles[0]
        assert c.cycle_index == 1
        assert c.start_price == pytest.approx(1.0)
        assert c.min_price == pytest.approx(0.9)
        assert c.max_price == pytest.approx(1.3)
        assert c.up_amplitude_pct == pytest.approx((1.3 / 0.9 - 1) * 100, rel=1e-6)
        assert c.down_amplitude_pct == pytest.approx((1.2 / 1.3 - 1) * 100, rel=1e-6)
        assert c.up_duration_s == pytest.approx(2 * 60.0)
        assert c.down_duration_s == pytest.approx(2 * 60.0)
        assert c.status == "confirmed"


def test_single_spike_not_confirmed_with_window(session_factory):
    prices = [1.0, 1.5, 1.0]
    with session_factory() as s:
        setup_series(s, "m2", prices)
        det = VariationDetector(s, 35.0, 3, 5.0)
        det.process("m2")
        s.commit()
        extremes = s.query(Extreme).filter(Extreme.confirmed.is_(True)).all()
        assert len(extremes) == 1
        counted = s.query(Movement).filter(Movement.counted.is_(True)).all()
        assert len(counted) == 0


def test_down_move_35_counted(session_factory):
    prices = [1.0, 1.05, 1.0, 0.6, 0.65, 0.58]
    with session_factory() as s:
        setup_series(s, "m3", prices)
        det = VariationDetector(s, 35.0, 2, 5.0)
        det.process("m3")
        s.commit()
        counted = s.query(Movement).filter(Movement.counted.is_(True)).all()
        assert len(counted) == 1
        assert counted[0].type == "down"
        assert counted[0].amplitude_pct == pytest.approx((0.6 / 1.05 - 1) * 100, rel=1e-6)
        assert counted[0].amplitude_pct <= -35.0


def test_reprocessing_is_idempotent(session_factory):
    prices = [1.0, 0.9, 0.95, 1.3, 1.25, 1.2, 1.3]
    with session_factory() as s:
        setup_series(s, "m4", prices)
        det = VariationDetector(s, 35.0, 2, 5.0)
        det.process("m4")
        s.commit()
        n_mov = s.query(Movement).count()
        n_ext = s.query(Extreme).count()
        det.process("m4")
        det.process("m4")
        s.commit()
        assert s.query(Movement).count() == n_mov
        assert s.query(Extreme).count() == n_ext
