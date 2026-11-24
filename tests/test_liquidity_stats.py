from datetime import datetime, timedelta, timezone

from scanner.liquidity import LiquidityAnalyzer
from scanner.models import LiquidityEvent, Observation, Token
from scanner.stats import StatsUpdater
from scanner.cycles import CycleDetector
from scanner.detector import VariationDetector

BASE = datetime(2025, 2, 1, tzinfo=timezone.utc)


def setup(s, mint, prices, liqs):
    s.add(Token(mint=mint, first_seen_at=BASE, threshold_usd=50000.0, status="tracked"))
    for i, (p, l) in enumerate(zip(prices, liqs)):
        s.add(Observation(mint=mint, ts=BASE + timedelta(minutes=i), price_usd=p, market_cap=100000.0, fdv=110000.0, liquidity_usd=l, volume_24h=1000.0, source="dexscreener"))
    s.commit()


def test_liquidity_decline_alert(session_factory):
    with session_factory() as s:
        setup(s, "liq1", [1.0] * 5, [100000.0, 90000.0, 80000.0, 60000.0, 50000.0])
        analyzer = LiquidityAnalyzer(s, low_usd=10000.0, decline_pct=30.0, window=5)
        event = analyzer.analyze("liq1")
        s.commit()
        assert event is not None
        assert event.alert is not None and "declining" in event.alert


def test_liquidity_low_alert(session_factory):
    with session_factory() as s:
        setup(s, "liq2", [1.0, 1.0], [8000.0, 7000.0])
        analyzer = LiquidityAnalyzer(s, low_usd=10000.0, decline_pct=90.0, window=5)
        event = analyzer.analyze("liq2")
        s.commit()
        assert event.alert is not None and "low" in event.alert


def test_stats_after_cycle(session_factory):
    with session_factory() as s:
        prices = [1.0, 0.9, 0.95, 1.3, 1.25, 1.2, 1.3]
        setup(s, "st1", prices, [100000.0] * 7)
        VariationDetector(s, 35.0, 2, 5.0).process("st1")
        CycleDetector(s, 35.0).process("st1")
        stats = StatsUpdater(s).update("st1")
        s.commit()
        assert stats.total_cycles == 1
        assert stats.confirmed_cycles == 1
        assert stats.avg_up_pct is not None and stats.avg_up_pct > 35.0
        assert stats.avg_down_pct is not None and stats.avg_down_pct < 0
        assert stats.avg_cycle_duration_s == 4 * 60.0
        assert stats.last_liquidity_usd == 100000.0
