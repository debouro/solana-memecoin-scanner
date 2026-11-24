from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Cycle, CycleState, Extreme, Observation, utcnow
from .series import observation_near, primary_source_for


class CycleDetector:
    def __init__(self, session: Session, threshold_pct: float, source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye"), up_threshold_pct: float | None = None, min_up_duration_s: float | None = None, max_up_duration_s: float | None = None, min_down_duration_s: float | None = None, max_down_duration_s: float | None = None, min_cycle_duration_s: float | None = None, max_cycle_duration_s: float | None = None):
        self.session = session
        self.threshold_pct = threshold_pct
        self.up_threshold_pct = up_threshold_pct if up_threshold_pct is not None else threshold_pct
        self.priority = source_priority
        self.min_up_duration_s = min_up_duration_s
        self.max_up_duration_s = max_up_duration_s
        self.min_down_duration_s = min_down_duration_s
        self.max_down_duration_s = max_down_duration_s
        self.min_cycle_duration_s = min_cycle_duration_s
        self.max_cycle_duration_s = max_cycle_duration_s

    def process(self, mint: str, source: str | None = None) -> int:
        if source is None:
            source = primary_source_for(self.session, mint, self.priority)
        state = self.session.get(CycleState, mint)
        if state is None:
            state = CycleState(mint=mint)
            self.session.add(state)
        stmt = select(Extreme).where(Extreme.mint == mint, Extreme.confirmed.is_(True)).order_by(Extreme.id.asc())
        if state.cursor_extreme_id is not None:
            stmt = stmt.where(Extreme.id > state.cursor_extreme_id)
        extremes = list(self.session.scalars(stmt).all())
        created = 0
        for extreme in extremes:
            state.cursor_extreme_id = extreme.id
            created += self._close_windows(mint, source)
        state.updated_at = utcnow()
        return created

    def _close_windows(self, mint: str, source: str | None) -> int:
        stmt = select(Extreme).where(Extreme.mint == mint, Extreme.confirmed.is_(True)).order_by(Extreme.id.desc()).limit(4)
        last4 = list(self.session.scalars(stmt).all())[::-1]
        if len(last4) < 4:
            return 0
        h1, l1, h2, l2 = last4
        if not (h1.kind == "high" and l1.kind == "low" and h2.kind == "high" and l2.kind == "low"):
            return 0
        exists = self.session.scalar(select(func.count(Cycle.id)).where(Cycle.mint == mint, Cycle.start_extreme_id == h1.id))
        if exists:
            return 0
        if l1.price <= 0 or h2.price <= 0:
            return 0
        up_amplitude = (h2.price - l1.price) / l1.price * 100.0
        if up_amplitude < self.up_threshold_pct:
            return 0
        down_amplitude = (l2.price - h2.price) / h2.price * 100.0
        up_duration = (h2.ts - l1.ts).total_seconds()
        down_duration = (l2.ts - h2.ts).total_seconds()
        cycle_duration = up_duration + down_duration
        if self.min_up_duration_s is not None and up_duration < self.min_up_duration_s:
            return 0
        if self.max_up_duration_s is not None and up_duration > self.max_up_duration_s:
            return 0
        if self.min_down_duration_s is not None and down_duration < self.min_down_duration_s:
            return 0
        if self.max_down_duration_s is not None and down_duration > self.max_down_duration_s:
            return 0
        if self.min_cycle_duration_s is not None and cycle_duration < self.min_cycle_duration_s:
            return 0
        if self.max_cycle_duration_s is not None and cycle_duration > self.max_cycle_duration_s:
            return 0
        index = self.session.scalar(select(func.count(Cycle.id)).where(Cycle.mint == mint)) or 0
        cycle = Cycle(
            mint=mint,
            cycle_index=index + 1,
            status="confirmed",
            start_extreme_id=h1.id,
            low_extreme_id=l1.id,
            high_extreme_id=h2.id,
            end_extreme_id=l2.id,
            start_price=h1.price,
            min_price=l1.price,
            max_price=h2.price,
            up_amplitude_pct=up_amplitude,
            down_amplitude_pct=down_amplitude,
            up_duration_s=up_duration,
            down_duration_s=down_duration,
            start_ts=h1.ts,
            low_ts=l1.ts,
            high_ts=h2.ts,
            end_ts=l2.ts,
            liquidity_at_start=self._liquidity_near(mint, h1.ts, source),
            liquidity_at_low=self._liquidity_near(mint, l1.ts, source),
            liquidity_at_high=self._liquidity_near(mint, h2.ts, source),
        )
        self.session.add(cycle)
        return 1

    def _liquidity_near(self, mint: str, ts, source: str | None) -> float | None:
        obs = observation_near(self.session, mint, ts, source=source)
        if obs is None:
            obs = observation_near(self.session, mint, ts, source=None)
        return obs.liquidity_usd if obs else None
