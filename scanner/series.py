from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Observation


def primary_source_for(session: Session, mint: str, priority: tuple) -> str | None:
    for name in priority:
        exists = session.scalar(select(Observation.id).where(Observation.mint == mint, Observation.source == name).limit(1))
        if exists is not None:
            return name
    any_source = session.scalar(select(Observation.source).where(Observation.mint == mint).limit(1))
    return any_source


def primary_observations(session: Session, mint: str, source: str | None = None, after: datetime | None = None) -> list[Observation]:
    stmt = select(Observation).where(Observation.mint == mint)
    if source is not None:
        stmt = stmt.where(Observation.source == source)
    if after is not None:
        stmt = stmt.where(Observation.ts > after)
    stmt = stmt.order_by(Observation.ts.asc(), Observation.id.asc())
    return list(session.scalars(stmt).all())


def latest_observation(session: Session, mint: str, source: str | None = None) -> Observation | None:
    stmt = select(Observation).where(Observation.mint == mint)
    if source is not None:
        stmt = stmt.where(Observation.source == source)
    stmt = stmt.order_by(Observation.ts.desc(), Observation.id.desc()).limit(1)
    return session.scalar(stmt)


def observation_near(session: Session, mint: str, ts: datetime, source: str | None = None) -> Observation | None:
    stmt = select(Observation).where(Observation.mint == mint, Observation.ts <= ts)
    if source is not None:
        stmt = stmt.where(Observation.source == source)
    stmt = stmt.order_by(Observation.ts.desc()).limit(1)
    before = session.scalar(stmt)
    stmt2 = select(Observation).where(Observation.mint == mint, Observation.ts > ts)
    if source is not None:
        stmt2 = stmt2.where(Observation.source == source)
    stmt2 = stmt2.order_by(Observation.ts.asc()).limit(1)
    after = session.scalar(stmt2)
    if before is None:
        return after
    if after is None:
        return before
    if (ts - before.ts).total_seconds() <= (after.ts - ts).total_seconds():
        return before
    return after
