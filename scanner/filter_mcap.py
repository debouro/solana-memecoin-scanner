from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Token, utcnow
from .sources.base import PairData


class MarketCapFilter:
    def __init__(self, threshold_usd: float, max_usd: float | None = None):
        self.threshold_usd = threshold_usd
        self.max_usd = max_usd

    def evaluate(self, session: Session, pair: PairData, now: datetime | None = None) -> Token:
        now = now or utcnow()
        token = session.get(Token, pair.mint)
        if token is None:
            token = Token(mint=pair.mint, first_seen_at=now, threshold_usd=self.threshold_usd, status="watchlist")
            session.add(token)
        if pair.name and not token.name:
            token.name = pair.name
        if pair.symbol and not token.symbol:
            token.symbol = pair.symbol
        if pair.pair_created_at and not token.created_at:
            token.created_at = pair.pair_created_at
            token.created_at_source = getattr(pair, "source_name", None) or "aggregator"
        sources = token.sources_json or {}
        if pair.dex:
            sources[pair.dex] = True
        token.sources_json = sources
        if pair.market_cap is not None:
            if token.max_market_cap is None or pair.market_cap > token.max_market_cap:
                token.max_market_cap = pair.market_cap
            if pair.market_cap >= self.threshold_usd and token.status == "watchlist":
                token.status = "tracked"
                token.first_crossed_threshold_at = now
        return token

    def list_tracked(self, session: Session) -> list[Token]:
        stmt = select(Token).where(Token.status == "tracked").order_by(Token.mint)
        return list(session.scalars(stmt).all())

    def list_watchlist(self, session: Session) -> list[Token]:
        stmt = select(Token).where(Token.status == "watchlist").order_by(Token.mint)
        return list(session.scalars(stmt).all())
