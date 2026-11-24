from scanner.collector import Collector
from scanner.models import DataQuality, Token
from scanner.sources.base import PairData


def test_source_coherence_flags_divergence(session_factory, settings):
    collector = Collector(settings, session_factory)
    with session_factory() as s:
        s.add(Token(mint="mintX", first_seen_at=__import__("scanner.models", fromlist=["utcnow"]).utcnow(), threshold_usd=50000.0, status="watchlist"))
        results = {
            "dexscreener": PairData(mint="mintX", price_usd=1.0, market_cap=100000.0, liquidity_usd=50000.0),
            "geckoterminal": PairData(mint="mintX", price_usd=2.0, market_cap=100000.0, liquidity_usd=50000.0),
        }
        collector._check_coherence(s, "mintX", results)
        s.commit()
        issues = s.query(DataQuality).filter(DataQuality.issue == "incoherent_sources").all()
        assert len(issues) == 1
        assert "price_usd" in issues[0].detail


def test_source_coherence_ok_when_close(session_factory, settings):
    collector = Collector(settings, session_factory)
    with session_factory() as s:
        results = {
            "dexscreener": PairData(mint="mintY", price_usd=1.00, market_cap=100000.0, liquidity_usd=50000.0),
            "geckoterminal": PairData(mint="mintY", price_usd=1.05, market_cap=102000.0, liquidity_usd=51000.0),
        }
        collector._check_coherence(s, "mintY", results)
        s.commit()
        issues = s.query(DataQuality).filter(DataQuality.issue == "incoherent_sources").all()
        assert len(issues) == 0
