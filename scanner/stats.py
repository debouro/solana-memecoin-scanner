from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Cycle, LiquidityEvent, TokenStats, utcnow


class StatsUpdater:
    def __init__(self, session: Session):
        self.session = session

    def update(self, mint: str) -> TokenStats:
        cycles = list(self.session.scalars(select(Cycle).where(Cycle.mint == mint)).all())
        confirmed = [c for c in cycles if c.status == "confirmed"]
        ups = [c.up_amplitude_pct for c in confirmed if c.up_amplitude_pct is not None]
        downs = [c.down_amplitude_pct for c in confirmed if c.down_amplitude_pct is not None]
        durations = [((c.up_duration_s or 0) + (c.down_duration_s or 0)) for c in confirmed]
        stats = self.session.get(TokenStats, mint)
        if stats is None:
            stats = TokenStats(mint=mint)
            self.session.add(stats)
        stats.total_cycles = len(cycles)
        stats.confirmed_cycles = len(confirmed)
        stats.avg_up_pct = sum(ups) / len(ups) if ups else None
        stats.avg_down_pct = sum(downs) / len(downs) if downs else None
        stats.avg_cycle_duration_s = sum(durations) / len(durations) if durations else None
        liq_stmt = select(LiquidityEvent).where(LiquidityEvent.mint == mint, LiquidityEvent.liquidity_usd.isnot(None)).order_by(LiquidityEvent.ts.asc())
        liq_events = list(self.session.scalars(liq_stmt).all())
        pairs = [(e.ts, e.liquidity_usd) for e in liq_events]
        if not pairs:
            from .models import Observation
            obs_stmt = select(Observation).where(Observation.mint == mint, Observation.liquidity_usd.isnot(None)).order_by(Observation.ts.asc())
            pairs = [(o.ts, o.liquidity_usd) for o in self.session.scalars(obs_stmt).all()]
        if pairs:
            stats.last_liquidity_usd = pairs[-1][1]
            if len(pairs) >= 2:
                first = pairs[0][1]
                last = pairs[-1][1]
                if first and first > 0:
                    change = (last - first) / first * 100.0
                    if change <= -30:
                        stats.liquidity_trend = "decreasing"
                    elif change >= 30:
                        stats.liquidity_trend = "increasing"
                    else:
                        stats.liquidity_trend = "stable"
        stats.updated_at = utcnow()
        return stats

    def recompute_all(self) -> int:
        mints = list(self.session.scalars(select(func.distinct(Cycle.mint))).all())
        from .models import Observation
        obs_mints = list(self.session.scalars(select(func.distinct(Observation.mint))).all())
        all_mints = sorted(set(mints) | set(obs_mints))
        for mint in all_mints:
            self.update(mint)
        return len(all_mints)
