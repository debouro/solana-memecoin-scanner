from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LiquidityEvent, Observation, utcnow
from .series import primary_source_for


class LiquidityAnalyzer:
    def __init__(self, session: Session, low_usd: float, decline_pct: float, window: int, source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye")):
        self.session = session
        self.low_usd = low_usd
        self.decline_pct = decline_pct
        self.window = max(2, window)
        self.priority = source_priority

    def analyze(self, mint: str, source: str | None = None) -> LiquidityEvent | None:
        if source is None:
            source = primary_source_for(self.session, mint, self.priority)
        if source is None:
            return None
        stmt = select(Observation).where(Observation.mint == mint, Observation.source == source).order_by(Observation.ts.desc(), Observation.id.desc()).limit(self.window)
        obs_list = list(self.session.scalars(stmt).all())[::-1]
        if not obs_list:
            return None
        latest = obs_list[-1]
        existing = self.session.scalar(select(LiquidityEvent).where(LiquidityEvent.mint == mint, LiquidityEvent.ts == latest.ts))
        if existing is not None:
            return existing
        delta_pct = None
        if len(obs_list) >= 2 and obs_list[-2].liquidity_usd is not None and latest.liquidity_usd is not None and obs_list[-2].liquidity_usd > 0:
            delta_pct = (latest.liquidity_usd - obs_list[-2].liquidity_usd) / obs_list[-2].liquidity_usd * 100.0
        alerts: list[str] = []
        values = [o.liquidity_usd for o in obs_list if o.liquidity_usd is not None]
        if latest.liquidity_usd is not None and latest.liquidity_usd < self.low_usd:
            alerts.append("low")
        if len(values) >= 2:
            oldest = values[0]
            newest = values[-1]
            if oldest > 0 and (newest - oldest) / oldest * 100.0 <= -self.decline_pct:
                alerts.append("declining")
        event = LiquidityEvent(
            mint=mint,
            ts=latest.ts,
            liquidity_usd=latest.liquidity_usd,
            delta_pct=delta_pct,
            alert=",".join(alerts) if alerts else None,
        )
        self.session.add(event)
        return event
