from scanner.filter_mcap import MarketCapFilter
from scanner.sources.base import PairData


def make_pair(mint, mcap, price=1.0):
    return PairData(mint=mint, price_usd=price, market_cap=mcap, fdv=mcap * 1.1, liquidity_usd=20000.0)


def test_crossing_threshold_tracks_once_and_never_resets(session_factory):
    with session_factory() as s:
        f = MarketCapFilter(50000.0)
        t = f.evaluate(s, make_pair("mintA", 40000.0))
        assert t.status == "watchlist"
        assert t.first_crossed_threshold_at is None
        t = f.evaluate(s, make_pair("mintA", 60000.0))
        assert t.status == "tracked"
        first = t.first_crossed_threshold_at
        assert first is not None
        t = f.evaluate(s, make_pair("mintA", 30000.0))
        assert t.status == "tracked"
        assert t.first_crossed_threshold_at == first
        assert t.max_market_cap == 60000.0


def test_no_duplicate_token_rows(session_factory):
    with session_factory() as s:
        f = MarketCapFilter(50000.0)
        f.evaluate(s, make_pair("mintB", 10000.0))
        f.evaluate(s, make_pair("mintB", 20000.0))
        s.commit()
        from scanner.models import Token
        rows = s.query(Token).filter(Token.mint == "mintB").all()
        assert len(rows) == 1
