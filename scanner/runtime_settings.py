import dataclasses
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import AppConfig, utcnow

OVERRIDABLE_FIELDS = {
    "mcap_threshold_usd": float,
    "mcap_max_usd": "float_opt",
    "variation_threshold_pct": float,
    "up_threshold_pct": "float_opt",
    "down_threshold_pct": "float_opt",
    "confirmation_window": int,
    "retracement_pct": float,
    "min_up_duration_s": "float_opt",
    "max_up_duration_s": "float_opt",
    "min_down_duration_s": "float_opt",
    "max_down_duration_s": "float_opt",
    "min_cycle_duration_s": "float_opt",
    "max_cycle_duration_s": "float_opt",
    "liquidity_low_usd": float,
    "liquidity_decline_pct": float,
    "liquidity_decline_window": int,
    "min_liquidity_usd": float,
    "min_volume_24h_usd": float,
    "max_liquidity_change_pct": "float_opt",
    "collect_interval_seconds": int,
    "analysis_interval_seconds": int,
    "refresh_interval_seconds": int,
    "max_tokens_watched": int,
    "discovery_pages": int,
    "source_coherence_tolerance_pct": float,
}

RANGES = {
    "mcap_threshold_usd": (0, 1e15),
    "mcap_max_usd": (0, 1e15),
    "variation_threshold_pct": (0.01, 1000),
    "up_threshold_pct": (0.01, 1000),
    "down_threshold_pct": (0.01, 1000),
    "confirmation_window": (1, 100),
    "retracement_pct": (0.01, 50),
    "collect_interval_seconds": (5, 86400),
    "analysis_interval_seconds": (0, 86400),
    "refresh_interval_seconds": (2, 3600),
    "max_tokens_watched": (1, 100000),
    "discovery_pages": (1, 20),
    "source_coherence_tolerance_pct": (0.1, 100),
    "liquidity_decline_window": (2, 1000),
    "min_liquidity_usd": (0, 1e15),
    "min_volume_24h_usd": (0, 1e15),
}

LAST_MODIFIED_KEY = "__last_modified__"


def _parse(field: str, raw):
    kind = OVERRIDABLE_FIELDS[field]
    if kind == "float_opt":
        if raw is None or raw == "" or raw == "null":
            return None
        return float(raw)
    if kind == "float":
        return float(raw)
    if kind == int:
        return int(raw)
    return raw


def validate_updates(updates: dict) -> dict:
    cleaned = {}
    for key, value in updates.items():
        if key not in OVERRIDABLE_FIELDS:
            raise ValueError(f"paramètre inconnu: {key}")
        parsed = _parse(key, value)
        if key in RANGES and parsed is not None:
            low, high = RANGES[key]
            if not (low <= parsed <= high):
                raise ValueError(f"{key} hors limites [{low}, {high}]: {parsed}")
        if key in ("mcap_max_usd",) and parsed is not None:
            pass
        cleaned[key] = parsed
    for dur_key in ("min_up_duration_s", "max_up_duration_s", "min_down_duration_s", "max_down_duration_s", "min_cycle_duration_s", "max_cycle_duration_s"):
        if dur_key in cleaned and cleaned[dur_key] is not None and cleaned[dur_key] < 0:
            raise ValueError(f"{dur_key} doit être positif ou nul")
    return cleaned


def get_overrides(session: Session) -> dict:
    rows = session.scalars(select(AppConfig)).all()
    return {r.key: json.loads(r.value) if r.value else None for r in rows if r.key != LAST_MODIFIED_KEY}


def last_modified(session: Session) -> datetime | None:
    row = session.get(AppConfig, LAST_MODIFIED_KEY)
    if row and row.value:
        try:
            return datetime.fromisoformat(json.loads(row.value))
        except (ValueError, TypeError):
            return None
    return None


def effective_settings(session: Session, base: Settings) -> Settings:
    overrides = get_overrides(session)
    if not overrides:
        return base
    return dataclasses.replace(base, **overrides)


def save_overrides(session: Session, updates: dict) -> dict:
    cleaned = validate_updates(updates)
    for key, value in cleaned.items():
        row = session.get(AppConfig, key)
        if row is None:
            row = AppConfig(key=key)
            session.add(row)
        row.value = json.dumps(value)
        row.updated_at = utcnow()
    stamp = session.get(AppConfig, LAST_MODIFIED_KEY)
    if stamp is None:
        stamp = AppConfig(key=LAST_MODIFIED_KEY)
        session.add(stamp)
    stamp.value = json.dumps(utcnow().isoformat())
    stamp.updated_at = utcnow()
    return cleaned


def reset_overrides(session: Session):
    for key in list(OVERRIDABLE_FIELDS) + [LAST_MODIFIED_KEY]:
        row = session.get(AppConfig, key)
        if row is not None:
            session.delete(row)


def resolve_thresholds(settings: Settings) -> tuple[float, float]:
    up = settings.up_threshold_pct if settings.up_threshold_pct is not None else settings.variation_threshold_pct
    down = settings.down_threshold_pct if settings.down_threshold_pct is not None else settings.variation_threshold_pct
    return up, down
