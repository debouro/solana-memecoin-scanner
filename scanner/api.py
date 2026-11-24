import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from .backtest import run_backtest
from .collector import Collector
from .config import Settings
from .models import AppConfig, Cycle, DataQuality, DetectorState, Extreme, Favorite, LiquidityEvent, Movement, Notification, Observation, ScanState, Simulation, SimulationTrade, Token, TokenStats
from .phase import compute_phase
from .runtime_settings import effective_settings, get_overrides, last_modified, reset_overrides, save_overrides, validate_updates
from .series import latest_observation, primary_source_for
from .sources.base import to_float


def _serialize(obj):
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_serialize(o) for o in obj]
    if isinstance(obj, tuple):
        return [_serialize(o) for o in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "__table__"):
        return {c.name: _serialize(getattr(obj, c.name)) for c in obj.__table__.columns}
    return obj


def create_app(session_factory, settings: Settings, collector: Collector | None = None) -> FastAPI:
    app = FastAPI(title="Solana Memecoin Scanner API", version="1.0.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "chain": "solana", "time": datetime.now().astimezone().isoformat()}

    @app.get("/config")
    def config():
        return settings.public_dict()

    @app.get("/tokens")
    def list_tokens(tracked: bool | None = Query(default=None), min_market_cap: float | None = Query(default=None), limit: int = Query(default=200, le=1000)):
        with session_factory() as session:
            stmt = select(Token).order_by(Token.mint.asc()).limit(limit)
            if tracked is not None:
                stmt = select(Token).where(Token.status == ("tracked" if tracked else "watchlist")).order_by(Token.mint.asc()).limit(limit)
            tokens = list(session.scalars(stmt).all())
            if min_market_cap is not None:
                tokens = [t for t in tokens if (t.max_market_cap or 0) >= min_market_cap]
            return [_serialize(t) for t in tokens]

    @app.post("/tokens/{mint}")
    def add_token(mint: str):
        with session_factory() as session:
            if collector is not None:
                token = collector.add_token(session, mint)
                session.commit()
                return _serialize(token)
            raise HTTPException(status_code=503, detail="collector non disponible")

    @app.get("/tokens/summary")
    def tokens_summary(
        search: str | None = None,
        sort: str = Query(default="mcap"),
        order: str = Query(default="desc"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=25, ge=1, le=200),
        min_mcap: float | None = None,
        min_volume: float | None = None,
        min_liquidity: float | None = None,
        phase: str | None = None,
        favorites_only: bool = False,
        tracked_only: bool = True,
    ):
        with session_factory() as session:
            eff = effective_settings(session, settings)
            stmt = select(Token)
            if tracked_only:
                stmt = stmt.where(Token.status == "tracked")
            if favorites_only:
                fav_mints = {f.mint for f in session.scalars(select(Favorite)).all()}
                stmt = stmt.where(Token.mint.in_(fav_mints)) if fav_mints else stmt.where(Token.mint == "__none__")
            tokens = list(session.scalars(stmt).all())
            if search:
                q = search.lower()
                tokens = [t for t in tokens if q in (t.mint or "").lower() or q in (t.name or "").lower() or q in (t.symbol or "").lower()]
            rows = []
            for t in tokens:
                src = primary_source_for(session, t.mint, eff.source_priority)
                latest = latest_observation(session, t.mint, source=src) or latest_observation(session, t.mint)
                stats = session.get(TokenStats, t.mint)
                ph = compute_phase(session, t.mint, source_priority=eff.source_priority)
                fav = session.get(Favorite, t.mint) is not None
                rows.append({
                    "mint": t.mint, "name": t.name, "symbol": t.symbol, "logo_url": t.logo_url,
                    "status": t.status, "created_at": t.created_at, "first_crossed_threshold_at": t.first_crossed_threshold_at,
                    "max_market_cap": t.max_market_cap, "favorite": fav,
                    "latest": _serialize(latest), "stats": _serialize(stats), "phase": ph,
                })
            if min_mcap is not None:
                rows = [r for r in rows if ((r["latest"] or {}).get("market_cap") or 0) >= min_mcap]
            if min_volume is not None:
                rows = [r for r in rows if ((r["latest"] or {}).get("volume_24h") or 0) >= min_volume]
            if min_liquidity is not None:
                rows = [r for r in rows if ((r["latest"] or {}).get("liquidity_usd") or 0) >= min_liquidity]
            if phase:
                rows = [r for r in rows if r["phase"]["phase"] == phase]
            sort_keys = {
                "mcap": lambda r: (r["latest"] or {}).get("market_cap") or 0,
                "price": lambda r: (r["latest"] or {}).get("price_usd") or 0,
                "volume": lambda r: (r["latest"] or {}).get("volume_24h") or 0,
                "liquidity": lambda r: (r["latest"] or {}).get("liquidity_usd") or 0,
                "amplitude": lambda r: (r["stats"] or {}).get("avg_up_pct") or 0,
                "cycles": lambda r: (r["stats"] or {}).get("total_cycles") or 0,
                "updated": lambda r: (r["latest"] or {}).get("ts") or "",
                "name": lambda r: (r["symbol"] or "").lower(),
            }
            key_fn = sort_keys.get(sort, sort_keys["mcap"])
            rows.sort(key=key_fn, reverse=(order == "desc"))
            total = len(rows)
            start = (page - 1) * page_size
            return {"total": total, "page": page, "page_size": page_size, "rows": rows[start:start + page_size]}

    @app.get("/tokens/{mint}")
    def get_token(mint: str):
        with session_factory() as session:
            token = session.get(Token, mint)
            if token is None:
                raise HTTPException(status_code=404, detail="token inconnu (mint)")
            return _serialize(token)

    @app.get("/tokens/{mint}/observations")
    def get_observations(mint: str, source: str | None = None, limit: int = Query(default=500, le=5000), since: datetime | None = None):
        with session_factory() as session:
            stmt = select(Observation).where(Observation.mint == mint)
            if source:
                stmt = stmt.where(Observation.source == source)
            if since:
                stmt = stmt.where(Observation.ts >= since)
            stmt = stmt.order_by(Observation.ts.desc()).limit(limit)
            return [_serialize(o) for o in session.scalars(stmt).all()]

    @app.get("/tokens/{mint}/extremes")
    def get_extremes(mint: str, confirmed: bool = True):
        with session_factory() as session:
            stmt = select(Extreme).where(Extreme.mint == mint)
            if confirmed:
                stmt = stmt.where(Extreme.confirmed.is_(True))
            stmt = stmt.order_by(Extreme.id.asc())
            return [_serialize(e) for e in session.scalars(stmt).all()]

    @app.get("/tokens/{mint}/movements")
    def get_movements(mint: str, counted_only: bool = False):
        with session_factory() as session:
            stmt = select(Movement).where(Movement.mint == mint)
            if counted_only:
                stmt = stmt.where(Movement.counted.is_(True))
            stmt = stmt.order_by(Movement.id.asc())
            return [_serialize(m) for m in session.scalars(stmt).all()]

    @app.get("/tokens/{mint}/cycles")
    def get_cycles(mint: str):
        with session_factory() as session:
            stmt = select(Cycle).where(Cycle.mint == mint).order_by(Cycle.cycle_index.asc())
            return [_serialize(c) for c in session.scalars(stmt).all()]

    @app.get("/tokens/{mint}/liquidity")
    def get_liquidity(mint: str, limit: int = Query(default=500, le=5000)):
        with session_factory() as session:
            stmt = select(LiquidityEvent).where(LiquidityEvent.mint == mint).order_by(LiquidityEvent.ts.desc()).limit(limit)
            return [_serialize(e) for e in session.scalars(stmt).all()]

    @app.get("/tokens/{mint}/stats")
    def get_stats(mint: str):
        with session_factory() as session:
            stats = session.get(TokenStats, mint)
            if stats is None:
                raise HTTPException(status_code=404, detail="aucune statistique")
            return _serialize(stats)

    @app.get("/alerts")
    def get_alerts(limit: int = Query(default=200, le=1000)):
        with session_factory() as session:
            liq = list(session.scalars(select(LiquidityEvent).where(LiquidityEvent.alert.isnot(None)).order_by(LiquidityEvent.ts.desc()).limit(limit)).all())
            quality = list(session.scalars(select(DataQuality).order_by(DataQuality.ts.desc()).limit(limit)).all())
            tokens = list(session.scalars(select(Token).where(Token.anomaly_flags.isnot(None))).all())
            return {
                "liquidity_alerts": [_serialize(e) for e in liq],
                "data_quality_issues": [_serialize(q) for q in quality],
                "anomalous_tokens": [_serialize(t) for t in tokens],
            }

    @app.post("/scan/run")
    def run_scan(background_tasks: BackgroundTasks):
        if collector is None:
            raise HTTPException(status_code=503, detail="collector non disponible")
        background_tasks.add_task(collector.collect_once)
        return {"status": "started"}

    @app.get("/settings")
    def get_settings():
        with session_factory() as session:
            eff = effective_settings(session, settings)
            return {"effective": eff.public_dict(), "overrides": get_overrides(session), "last_modified": last_modified(session)}

    @app.put("/settings")
    def put_settings(payload: dict = Body(...)):
        with session_factory() as session:
            try:
                save_overrides(session, payload)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            session.commit()
            eff = effective_settings(session, settings)
            return {"ok": True, "effective": eff.public_dict(), "overrides": get_overrides(session), "last_modified": last_modified(session)}

    @app.post("/settings/reset")
    def post_settings_reset():
        with session_factory() as session:
            reset_overrides(session)
            session.commit()
            eff = effective_settings(session, settings)
            return {"ok": True, "effective": eff.public_dict(), "overrides": {}, "last_modified": None}

    @app.get("/favorites")
    def list_favorites():
        with session_factory() as session:
            favs = list(session.scalars(select(Favorite).order_by(Favorite.added_at.desc())).all())
            out = []
            for f in favs:
                token = session.get(Token, f.mint)
                out.append({"mint": f.mint, "added_at": f.added_at, "token": _serialize(token)})
            return out

    @app.post("/favorites/{mint}")
    def add_favorite(mint: str):
        with session_factory() as session:
            if session.get(Token, mint) is None:
                session.add(Token(mint=mint, first_seen_at=datetime.now(timezone.utc), threshold_usd=settings.mcap_threshold_usd, status="watchlist"))
            if session.get(Favorite, mint) is None:
                session.add(Favorite(mint=mint))
            session.commit()
            return {"ok": True, "mint": mint}

    @app.delete("/favorites/{mint}")
    def remove_favorite(mint: str):
        with session_factory() as session:
            fav = session.get(Favorite, mint)
            if fav is None:
                raise HTTPException(status_code=404, detail="favori introuvable")
            session.delete(fav)
            session.commit()
            return {"ok": True, "mint": mint}

    @app.get("/notifications")
    def list_notifications(limit: int = Query(default=200, le=1000), unread_only: bool = False):
        with session_factory() as session:
            stmt = select(Notification).order_by(Notification.ts.desc()).limit(limit)
            if unread_only:
                stmt = select(Notification).where(Notification.read.is_(False)).order_by(Notification.ts.desc()).limit(limit)
            notes = list(session.scalars(stmt).all())
            unread = session.scalar(select(func.count(Notification.id)).where(Notification.read.is_(False))) or 0
            return {"unread": unread, "items": [_serialize(n) for n in notes]}

    @app.post("/notifications/{note_id}/read")
    def read_notification(note_id: int):
        with session_factory() as session:
            note = session.get(Notification, note_id)
            if note is None:
                raise HTTPException(status_code=404, detail="notification introuvable")
            note.read = True
            session.commit()
            return {"ok": True}

    @app.post("/notifications/read-all")
    def read_all_notifications():
        with session_factory() as session:
            for n in session.scalars(select(Notification).where(Notification.read.is_(False))).all():
                n.read = True
            session.commit()
            return {"ok": True}

    @app.get("/stats/global")
    def global_stats():
        with session_factory() as session:
            eff = effective_settings(session, settings)
            total = session.scalar(select(func.count(Token.mint))) or 0
            watchlist = session.scalar(select(func.count(Token.mint)).where(Token.status == "watchlist")) or 0
            tracked = session.scalar(select(func.count(Token.mint)).where(Token.status == "tracked")) or 0
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            new_today = session.scalar(select(func.count(Token.mint)).where(Token.first_seen_at >= today)) or 0
            cycles_today = session.scalar(select(func.count(Cycle.id)).where(Cycle.high_ts.isnot(None), Cycle.high_ts >= today)) or 0
            tracked_tokens = list(session.scalars(select(Token).where(Token.status == "tracked")).all())
            passed = 0
            phases = {"up": 0, "down": 0, "consolidation": 0, "new_cycle": 0, "insufficient": 0}
            for t in tracked_tokens:
                src = primary_source_for(session, t.mint, eff.source_priority)
                latest = latest_observation(session, t.mint, source=src) or latest_observation(session, t.mint)
                ok = latest is not None and (latest.market_cap or 0) >= eff.mcap_threshold_usd
                if eff.mcap_max_usd is not None and (latest.market_cap or 0) > eff.mcap_max_usd:
                    ok = False
                if (latest.liquidity_usd or 0) < eff.min_liquidity_usd:
                    ok = False
                if (latest.volume_24h or 0) < eff.min_volume_24h_usd:
                    ok = False
                if ok:
                    passed += 1
                phase = compute_phase(session, t.mint, source_priority=eff.source_priority)
                phases[phase["phase"]] = phases.get(phase["phase"], 0) + 1
            last_scan = session.get(ScanState, "last_scan")
            status = session.get(ScanState, "scanner_status")
            unread = session.scalar(select(func.count(Notification.id)).where(Notification.read.is_(False))) or 0
            return {
                "tokens_total": total,
                "tokens_watchlist": watchlist,
                "tokens_tracked": tracked,
                "tokens_passed_filters": passed,
                "new_tokens_today": new_today,
                "cycles_today": cycles_today,
                "phases": phases,
                "scanner_status": status.value if status else "unknown",
                "last_scan": json.loads(last_scan.value) if last_scan and last_scan.value else None,
                "unread_notifications": unread,
                "threshold_usd": eff.mcap_threshold_usd,
            }

    @app.get("/tokens/{mint}/phase")
    def token_phase(mint: str):
        with session_factory() as session:
            eff = effective_settings(session, settings)
            if session.get(Token, mint) is None:
                raise HTTPException(status_code=404, detail="token inconnu (mint)")
            return compute_phase(session, mint, source_priority=eff.source_priority)

    def _ath_atl(session, mint: str, source: str | None):
        stmt = select(Observation).where(Observation.mint == mint, Observation.price_usd.isnot(None))
        if source:
            stmt = stmt.where(Observation.source == source)
        obs = list(session.scalars(stmt).all())
        if not obs:
            return None
        ath = max(obs, key=lambda o: o.price_usd)
        atl = min(obs, key=lambda o: o.price_usd)
        latest = latest_observation(session, mint, source=source) or obs[-1]
        return {
            "ath": ath.price_usd, "ath_ts": ath.ts,
            "atl": atl.price_usd, "atl_ts": atl.ts,
            "current_price": latest.price_usd,
            "vs_ath_pct": ((latest.price_usd - ath.price_usd) / ath.price_usd * 100.0) if latest.price_usd and ath.price_usd else None,
            "vs_atl_pct": ((latest.price_usd - atl.price_usd) / atl.price_usd * 100.0) if latest.price_usd and atl.price_usd else None,
            "note": "Valeurs calculées sur l'historique collecté uniquement ; ce ne sont pas nécessairement les extrêmes absolus depuis la création du token.",
        }

    @app.get("/tokens/{mint}/ath-atl")
    def token_ath_atl(mint: str):
        with session_factory() as session:
            eff = effective_settings(session, settings)
            if session.get(Token, mint) is None:
                raise HTTPException(status_code=404, detail="token inconnu (mint)")
            source = primary_source_for(session, mint, eff.source_priority)
            return _ath_atl(session, mint, source)

    @app.get("/tokens/{mint}/chart")
    def token_chart(mint: str, tf: str = Query(default="all")):
        with session_factory() as session:
            eff = effective_settings(session, settings)
            if session.get(Token, mint) is None:
                raise HTTPException(status_code=404, detail="token inconnu (mint)")
            source = primary_source_for(session, mint, eff.source_priority)
            tfs = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "24h": 86400, "7d": 604800, "all": None}
            if tf not in tfs:
                raise HTTPException(status_code=422, detail=f"tf invalide, valeurs: {list(tfs)}")
            bucket = tfs[tf]
            stmt = select(Observation).where(Observation.mint == mint, Observation.price_usd.isnot(None))
            if source:
                stmt = stmt.where(Observation.source == source)
            obs = list(session.scalars(stmt.order_by(Observation.ts.asc())).all())
            candles = []
            if bucket:
                buckets: dict[int, list] = {}
                for o in obs:
                    key = int(o.ts.timestamp()) // bucket * bucket
                    buckets.setdefault(key, []).append(o.price_usd)
                for key in sorted(buckets):
                    prices = buckets[key]
                    candles.append({"time": key, "open": prices[0], "high": max(prices), "low": min(prices), "close": prices[-1]})
            else:
                for o in obs:
                    candles.append({"time": int(o.ts.timestamp()), "open": o.price_usd, "high": o.price_usd, "low": o.price_usd, "close": o.price_usd})
            extremes = list(session.scalars(select(Extreme).where(Extreme.mint == mint, Extreme.confirmed.is_(True)).order_by(Extreme.id.asc())).all())
            movements = list(session.scalars(select(Movement).where(Movement.mint == mint, Movement.counted.is_(True)).order_by(Movement.id.asc())).all())
            cycles = list(session.scalars(select(Cycle).where(Cycle.mint == mint).order_by(Cycle.cycle_index.asc())).all())
            return {
                "tf": tf,
                "candles": candles,
                "extremes": [{"id": e.id, "time": int(e.ts.timestamp()), "kind": e.kind, "price": e.price} for e in extremes],
                "movements": [{"id": m.id, "type": m.type, "time": int(m.end_ts.timestamp()), "amplitude_pct": m.amplitude_pct, "start_price": m.start_price, "end_price": m.end_price} for m in movements],
                "cycles": [{"id": c.id, "cycle_index": c.cycle_index, "low_time": int(c.low_ts.timestamp()) if c.low_ts else None, "high_time": int(c.high_ts.timestamp()) if c.high_ts else None, "start_time": int(c.start_ts.timestamp()) if c.start_ts else None, "end_time": int(c.end_ts.timestamp()) if c.end_ts else None, "min_price": c.min_price, "max_price": c.max_price, "up_amplitude_pct": c.up_amplitude_pct, "down_amplitude_pct": c.down_amplitude_pct} for c in cycles],
            }

    @app.get("/tokens/{mint}/overview")
    def token_overview(mint: str):
        with session_factory() as session:
            eff = effective_settings(session, settings)
            token = session.get(Token, mint)
            if token is None:
                raise HTTPException(status_code=404, detail="token inconnu (mint)")
            source = primary_source_for(session, mint, eff.source_priority)
            latest = latest_observation(session, mint, source=source) or latest_observation(session, mint)
            stats = session.get(TokenStats, mint)
            phase = compute_phase(session, mint, source_priority=eff.source_priority)
            ath_atl = _ath_atl(session, mint, source)
            fav = session.get(Favorite, mint) is not None
            cycles_count = session.scalar(select(func.count(Cycle.id)).where(Cycle.mint == mint)) or 0
            return {
                "token": _serialize(token),
                "latest": _serialize(latest),
                "stats": _serialize(stats),
                "phase": phase,
                "ath_atl": ath_atl,
                "favorite": fav,
                "cycles_count": cycles_count,
            }

    @app.post("/backtest/run")
    def backtest_run(payload: dict = Body(...)):
        mint = payload.get("mint")
        if not mint:
            raise HTTPException(status_code=422, detail="champ 'mint' requis")
        with session_factory() as session:
            eff = effective_settings(session, settings)
            try:
                result = run_backtest(
                    session,
                    mint=mint,
                    capital=float(payload.get("capital", 100.0)),
                    take_profit_pct=float(payload.get("take_profit_pct", 30.0)),
                    stop_loss_pct=float(payload.get("stop_loss_pct", 20.0)),
                    fees_pct=float(payload.get("fees_pct", 0.5)),
                    slippage_pct=float(payload.get("slippage_pct", 1.0)),
                    time_from=datetime.fromisoformat(payload["time_from"]) if payload.get("time_from") else None,
                    time_to=datetime.fromisoformat(payload["time_to"]) if payload.get("time_to") else None,
                    max_cycles=int(payload["max_cycles"]) if payload.get("max_cycles") else None,
                    entry_mode=payload.get("entry_mode", "low_confirmation"),
                    source_priority=eff.source_priority,
                    store=True,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            session.commit()
            return result

    @app.post("/backtest/compare")
    def backtest_compare(payload: dict = Body(...)):
        mint = payload.get("mint")
        configs = payload.get("configs") or []
        if not mint or not configs:
            raise HTTPException(status_code=422, detail="champs 'mint' et 'configs' requis")
        results = []
        with session_factory() as session:
            eff = effective_settings(session, settings)
            for cfg in configs:
                try:
                    r = run_backtest(session, mint=mint, source_priority=eff.source_priority, store=True, **{k: v for k, v in cfg.items() if k != "mint"})
                    results.append({"config": r["config"], "summary": r["summary"], "insufficient_data": r["insufficient_data"], "simulation_id": r.get("simulation_id")})
                except ValueError as exc:
                    results.append({"config": cfg, "error": str(exc)})
            session.commit()
            return {"mint": mint, "results": results}

    @app.get("/backtest/simulations")
    def backtest_list(mint: str | None = None, limit: int = Query(default=100, le=500)):
        with session_factory() as session:
            stmt = select(Simulation).order_by(Simulation.created_at.desc()).limit(limit)
            if mint:
                stmt = select(Simulation).where(Simulation.mint == mint).order_by(Simulation.created_at.desc()).limit(limit)
            sims = list(session.scalars(stmt).all())
            return [{"id": s.id, "mint": s.mint, "created_at": s.created_at, "config": json.loads(s.config_json), "insufficient_data": s.insufficient_data, "note": s.note, "summary": (json.loads(s.results_json).get("summary") if s.results_json else None)} for s in sims]

    @app.get("/backtest/simulations/{sim_id}")
    def backtest_detail(sim_id: int):
        with session_factory() as session:
            sim = session.get(Simulation, sim_id)
            if sim is None:
                raise HTTPException(status_code=404, detail="simulation introuvable")
            trades = list(session.scalars(select(SimulationTrade).where(SimulationTrade.simulation_id == sim_id).order_by(SimulationTrade.entry_ts.asc())).all())
            return {"simulation": _serialize(sim), "trades": [_serialize(t) for t in trades]}

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(os.path.join(static_dir, "index.html"))

    return app
