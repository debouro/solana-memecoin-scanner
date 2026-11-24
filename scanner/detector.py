from sqlalchemy.orm import Session

from .models import DetectorState, Extreme, Movement, Observation, utcnow
from .series import primary_observations, primary_source_for


class VariationDetector:
    def __init__(self, session: Session, threshold_pct: float, confirmation_window: int, retracement_pct: float, source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye"), up_threshold_pct: float | None = None, down_threshold_pct: float | None = None):
        self.session = session
        self.threshold_pct = threshold_pct
        self.up_threshold_pct = up_threshold_pct if up_threshold_pct is not None else threshold_pct
        self.down_threshold_pct = down_threshold_pct if down_threshold_pct is not None else threshold_pct
        self.window = max(1, confirmation_window)
        self.retracement = retracement_pct / 100.0
        self.priority = source_priority

    def process(self, mint: str, source: str | None = None) -> int:
        if source is None:
            source = primary_source_for(self.session, mint, self.priority)
        if source is None:
            return 0
        state = self.session.get(DetectorState, mint)
        if state is None:
            state = DetectorState(mint=mint)
            self.session.add(state)
        after = state.last_ts_processed
        obs_list = primary_observations(self.session, mint, source=source, after=after)
        processed = 0
        for obs in obs_list:
            if self._ingest(state, obs):
                processed += 1
        state.updated_at = utcnow()
        return processed

    def _ingest(self, state: DetectorState, obs: Observation) -> bool:
        price = obs.price_usd
        if price is None or price <= 0:
            state.last_ts_processed = obs.ts
            return False
        ts = obs.ts
        if state.last_extreme_id is None:
            extreme = Extreme(mint=state.mint, ts=ts, kind="high", price=price, confirmed=True, obs_count=1, confirmed_at=ts)
            self.session.add(extreme)
            self.session.flush()
            state.last_extreme_id = extreme.id
            state.direction = "down"
            state.candidate_kind = "low"
            state.candidate_price = price
            state.candidate_ts = ts
            state.candidate_count = 1
            state.last_ts_processed = ts
            return True
        if state.direction == "up":
            if price >= state.candidate_price:
                state.candidate_price = price
                state.candidate_ts = ts
                state.candidate_count = 1
            else:
                state.candidate_count += 1
                if state.candidate_price is not None and price <= state.candidate_price * (1 - self.retracement) and state.candidate_count >= self.window:
                    self._confirm(state, "high", obs)
        else:
            if price <= state.candidate_price:
                state.candidate_price = price
                state.candidate_ts = ts
                state.candidate_count = 1
            else:
                state.candidate_count += 1
                if state.candidate_price is not None and price >= state.candidate_price * (1 + self.retracement) and state.candidate_count >= self.window:
                    self._confirm(state, "low", obs)
        state.last_ts_processed = ts
        return True

    def _confirm(self, state: DetectorState, kind: str, obs: Observation) -> None:
        last = self.session.get(Extreme, state.last_extreme_id)
        candidate_price = state.candidate_price
        candidate_ts = state.candidate_ts
        candidate_count = state.candidate_count
        extreme = Extreme(mint=state.mint, ts=candidate_ts, kind=kind, price=candidate_price, confirmed=True, obs_count=candidate_count, confirmed_at=obs.ts)
        self.session.add(extreme)
        self.session.flush()
        if last is not None and last.price and last.price > 0:
            amplitude = (candidate_price - last.price) / last.price * 100.0
            threshold_used = self.up_threshold_pct if kind == "high" else self.down_threshold_pct
            counted = (kind == "high" and amplitude >= threshold_used) or (kind == "low" and amplitude <= -threshold_used)
            movement = Movement(
                mint=state.mint,
                type="up" if kind == "high" else "down",
                from_extreme_id=last.id,
                to_extreme_id=extreme.id,
                start_price=last.price,
                end_price=candidate_price,
                amplitude_pct=amplitude,
                start_ts=last.ts,
                end_ts=candidate_ts,
                threshold_pct=threshold_used,
                counted=counted,
            )
            self.session.add(movement)
        state.last_extreme_id = extreme.id
        state.direction = "down" if kind == "high" else "up"
        state.candidate_kind = "low" if kind == "high" else "high"
        state.candidate_price = obs.price_usd
        state.candidate_ts = obs.ts
        state.candidate_count = 1
