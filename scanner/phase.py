from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Cycle, DetectorState, Extreme, Movement, Observation
from .series import latest_observation, primary_source_for


def compute_phase(session: Session, mint: str, new_cycle_window_s: float = 3600.0, source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye")) -> dict:
    state = session.get(DetectorState, mint)
    extremes = list(session.scalars(select(Extreme).where(Extreme.mint == mint, Extreme.confirmed.is_(True)).order_by(Extreme.id.asc())).all())
    if state is None or len(extremes) < 2:
        return {"phase": "insufficient", "label": "Données insuffisantes", "direction": None, "detail": "Pas assez d'observations confirmées pour déterminer une phase."}
    last_extreme = extremes[-1]
    source = primary_source_for(session, mint, source_priority)
    latest = latest_observation(session, mint, source=source) or latest_observation(session, mint)
    now = datetime.now(timezone.utc)
    recent_cycle = session.scalar(
        select(Cycle).where(Cycle.mint == mint, Cycle.status == "confirmed", Cycle.high_ts.isnot(None)).order_by(Cycle.high_ts.desc()).limit(1)
    )
    new_cycle = bool(recent_cycle and recent_cycle.high_ts and (now - recent_cycle.high_ts.replace(tzinfo=timezone.utc) if recent_cycle.high_ts.tzinfo is None else now - recent_cycle.high_ts).total_seconds() <= new_cycle_window_s)
    movements = list(session.scalars(select(Movement).where(Movement.mint == mint, Movement.counted.is_(True), Movement.to_extreme_id == last_extreme.id)).all())
    direction = state.direction
    current_price = latest.price_usd if latest else None
    change_since_extreme = None
    if current_price and last_extreme.price:
        change_since_extreme = (current_price - last_extreme.price) / last_extreme.price * 100.0
    if new_cycle:
        phase = "new_cycle"
        label = "Nouveau cycle détecté"
    elif movements:
        phase = "up" if movements[-1].type == "up" else "down"
        label = "Phase ascendante" if phase == "up" else "Phase descendante"
    elif change_since_extreme is not None and abs(change_since_extreme) < 5.0:
        phase = "consolidation"
        label = "Consolidation"
    else:
        phase = direction or "consolidation"
        label = "Phase ascendante" if phase == "up" else ("Phase descendante" if phase == "down" else "Consolidation")
    return {
        "phase": phase,
        "label": label,
        "direction": direction,
        "last_extreme_kind": last_extreme.kind,
        "last_extreme_price": last_extreme.price,
        "last_extreme_ts": last_extreme.ts,
        "current_price": current_price,
        "change_since_extreme_pct": change_since_extreme,
    }
