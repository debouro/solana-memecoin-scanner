from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Token(Base):
    __tablename__ = "tokens"

    mint: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(256))
    symbol: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at_source: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    threshold_usd: Mapped[float] = mapped_column(Float, default=50000.0)
    first_crossed_threshold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="watchlist", index=True)
    max_market_cap: Mapped[float | None] = mapped_column(Float)
    anomaly_flags: Mapped[list | None] = mapped_column(JSON)
    sources_json: Mapped[dict | None] = mapped_column(JSON)
    logo_url: Mapped[str | None] = mapped_column(String(512))


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("mint", "ts", "source", name="uq_obs_mint_ts_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    price_usd: Mapped[float | None] = mapped_column(Float)
    market_cap: Mapped[float | None] = mapped_column(Float)
    fdv: Mapped[float | None] = mapped_column(Float)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    volume_24h: Mapped[float | None] = mapped_column(Float)
    txns_buys: Mapped[int | None] = mapped_column(Integer)
    txns_sells: Mapped[int | None] = mapped_column(Integer)
    buyers: Mapped[int | None] = mapped_column(Integer)
    sellers: Mapped[int | None] = mapped_column(Integer)
    price_change_m5: Mapped[float | None] = mapped_column(Float)
    price_change_h1: Mapped[float | None] = mapped_column(Float)
    price_change_h24: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), index=True)
    raw_json: Mapped[str | None] = mapped_column(Text)


class Extreme(Base):
    __tablename__ = "extremes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    obs_count: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Movement(Base):
    __tablename__ = "movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    type: Mapped[str] = mapped_column(String(8))
    from_extreme_id: Mapped[int] = mapped_column(ForeignKey("extremes.id"))
    to_extreme_id: Mapped[int] = mapped_column(ForeignKey("extremes.id"))
    start_price: Mapped[float] = mapped_column(Float)
    end_price: Mapped[float] = mapped_column(Float)
    amplitude_pct: Mapped[float] = mapped_column(Float)
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    threshold_pct: Mapped[float] = mapped_column(Float)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    cycle_index: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="confirmed")
    start_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    low_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    high_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    end_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    start_price: Mapped[float | None] = mapped_column(Float)
    min_price: Mapped[float | None] = mapped_column(Float)
    max_price: Mapped[float | None] = mapped_column(Float)
    up_amplitude_pct: Mapped[float | None] = mapped_column(Float)
    down_amplitude_pct: Mapped[float | None] = mapped_column(Float)
    up_duration_s: Mapped[float | None] = mapped_column(Float)
    down_duration_s: Mapped[float | None] = mapped_column(Float)
    start_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    low_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    high_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    liquidity_at_start: Mapped[float | None] = mapped_column(Float)
    liquidity_at_low: Mapped[float | None] = mapped_column(Float)
    liquidity_at_high: Mapped[float | None] = mapped_column(Float)


class LiquidityEvent(Base):
    __tablename__ = "liquidity_events"
    __table_args__ = (UniqueConstraint("mint", "ts", name="uq_liq_mint_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    liquidity_usd: Mapped[float | None] = mapped_column(Float)
    delta_pct: Mapped[float | None] = mapped_column(Float)
    alert: Mapped[str | None] = mapped_column(String(64))


class TokenStats(Base):
    __tablename__ = "token_stats"

    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), primary_key=True)
    total_cycles: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_cycles: Mapped[int] = mapped_column(Integer, default=0)
    avg_up_pct: Mapped[float | None] = mapped_column(Float)
    avg_down_pct: Mapped[float | None] = mapped_column(Float)
    avg_cycle_duration_s: Mapped[float | None] = mapped_column(Float)
    last_liquidity_usd: Mapped[float | None] = mapped_column(Float)
    liquidity_trend: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataQuality(Base):
    __tablename__ = "data_quality"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str | None] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    source: Mapped[str | None] = mapped_column(String(32))
    issue: Mapped[str] = mapped_column(String(64))
    detail: Mapped[str | None] = mapped_column(Text)


class DetectorState(Base):
    __tablename__ = "detector_state"

    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), primary_key=True)
    last_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    direction: Mapped[str | None] = mapped_column(String(8))
    candidate_kind: Mapped[str | None] = mapped_column(String(8))
    candidate_price: Mapped[float | None] = mapped_column(Float)
    candidate_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    last_ts_processed: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CycleState(Base):
    __tablename__ = "cycle_state"

    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), primary_key=True)
    cursor_extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScanState(Base):
    __tablename__ = "scan_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class Favorite(Base):
    __tablename__ = "favorites"

    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    mint: Mapped[str | None] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    config_json: Mapped[str] = mapped_column(Text)
    results_json: Mapped[str] = mapped_column(Text)
    insufficient_data: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(Text)


class SimulationTrade(Base):
    __tablename__ = "simulation_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[int] = mapped_column(ForeignKey("simulations.id"), index=True)
    mint: Mapped[str] = mapped_column(String(64), ForeignKey("tokens.mint"), index=True)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price: Mapped[float] = mapped_column(Float)
    exit_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float)
    gross_pct: Mapped[float | None] = mapped_column(Float)
    fees_usd: Mapped[float | None] = mapped_column(Float)
    slippage_usd: Mapped[float | None] = mapped_column(Float)
    net_pct: Mapped[float | None] = mapped_column(Float)
    net_amount: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))
    entry_signal: Mapped[str | None] = mapped_column(String(64))
    extreme_id: Mapped[int | None] = mapped_column(ForeignKey("extremes.id"))
    cycle_id: Mapped[int | None] = mapped_column(ForeignKey("cycles.id"))
