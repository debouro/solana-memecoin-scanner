import json
import time
import traceback
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .cycles import CycleDetector
from .config import Settings
from .detector import VariationDetector
from .filter_mcap import MarketCapFilter
from .liquidity import LiquidityAnalyzer
from .models import Cycle, DataQuality, Movement, Observation, ScanState, Token, utcnow
from .notifications import Notifier
from .runtime_settings import effective_settings, resolve_thresholds
from .sources import build_rpc, build_sources
from .sources.base import BaseSource, PairData
from .stats import StatsUpdater


class Collector:
    def __init__(self, settings: Settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory
        self.sources: dict[str, BaseSource] = build_sources(settings)
        self.rpc = build_rpc(settings)
        self.filter = MarketCapFilter(settings.mcap_threshold_usd)

    def _analyzers(self, session: Session, eff: Settings):
        up_thr, down_thr = resolve_thresholds(eff)
        detector = VariationDetector(session, eff.variation_threshold_pct, eff.confirmation_window, eff.retracement_pct, eff.source_priority, up_threshold_pct=up_thr, down_threshold_pct=down_thr)
        cycles = CycleDetector(session, eff.variation_threshold_pct, eff.source_priority, up_threshold_pct=up_thr, min_up_duration_s=eff.min_up_duration_s, max_up_duration_s=eff.max_up_duration_s, min_down_duration_s=eff.min_down_duration_s, max_down_duration_s=eff.max_down_duration_s, min_cycle_duration_s=eff.min_cycle_duration_s, max_cycle_duration_s=eff.max_cycle_duration_s)
        liquidity = LiquidityAnalyzer(session, eff.liquidity_low_usd, eff.liquidity_decline_pct, eff.liquidity_decline_window, eff.source_priority)
        stats = StatsUpdater(session)
        return detector, cycles, liquidity, stats

    def _log_quality(self, session: Session, issue: str, detail: str, mint: str | None = None, source: str | None = None):
        session.add(DataQuality(mint=mint, source=source, issue=issue, detail=detail[:2000]))

    def discover_candidates(self, session: Session, eff: Settings, notifier: Notifier | None = None) -> int:
        added = 0
        for name in eff.source_priority:
            source = self.sources.get(name)
            if source is None:
                continue
            try:
                discovered = source.discover(eff.discovery_pages)
            except Exception as exc:
                self._log_quality(session, "discovery_error", f"{name}: {exc}", source=name)
                if notifier:
                    notifier.emit("connection_error", f"Erreur de connexion à la source {name}: {exc}")
                continue
            for item in discovered:
                existing = session.get(Token, item.mint)
                if existing is None:
                    token = Token(mint=item.mint, first_seen_at=utcnow(), threshold_usd=eff.mcap_threshold_usd, status="watchlist", name=item.name, symbol=item.symbol, created_at=item.pair_created_at, created_at_source=name)
                    session.add(token)
                    added += 1
        if added and notifier:
            notifier.emit("new_token", f"{added} nouveau(x) token(s) détecté(s) et ajouté(s) à la watchlist.")
        return added

    def add_token(self, session: Session, mint: str) -> Token:
        token = session.get(Token, mint)
        if token is None:
            token = Token(mint=mint, first_seen_at=utcnow(), threshold_usd=self.settings.mcap_threshold_usd, status="watchlist")
            session.add(token)
        return token

    def _fetch_all(self, session: Session, mint: str) -> dict[str, PairData]:
        results: dict[str, PairData] = {}
        for name in self.settings.source_priority:
            source = self.sources.get(name)
            if source is None:
                continue
            try:
                pair = source.fetch_token(mint)
            except Exception as exc:
                self._log_quality(session, "fetch_error", f"{name}: {exc}", mint=mint, source=name)
                continue
            if pair is not None and pair.chain == "solana":
                pair.raw = dict(pair.raw or {})
                pair.raw["_source"] = name
                results[name] = pair
        return results

    def _check_coherence(self, session: Session, mint: str, results: dict[str, PairData], tolerance_pct: float = 20.0):
        names = [n for n in self.settings.source_priority if n in results]
        if len(names) < 2:
            return
        primary = results[names[0]]
        for other_name in names[1:]:
            other = results[other_name]
            for field in ("price_usd", "market_cap", "liquidity_usd"):
                a = getattr(primary, field)
                b = getattr(other, field)
                if a is None or b is None or a <= 0 or b <= 0:
                    continue
                diff = abs(a - b) / max(a, b) * 100.0
                if diff > tolerance_pct:
                    self._log_quality(
                        session,
                        "incoherent_sources",
                        f"{field}: {names[0]}={a} vs {other_name}={b} ({diff:.1f}%)",
                        mint=mint,
                        source=f"{names[0]}+{other_name}",
                    )

    def _store_observation(self, session: Session, mint: str, ts: datetime, name: str, pair: PairData, raw_all: dict) -> Observation | None:
        existing = session.scalar(select(Observation).where(Observation.mint == mint, Observation.ts == ts, Observation.source == name))
        if existing is not None:
            return existing
        obs = Observation(
            mint=mint,
            ts=ts,
            price_usd=pair.price_usd,
            market_cap=pair.market_cap,
            fdv=pair.fdv,
            liquidity_usd=pair.liquidity_usd,
            volume_24h=pair.volume_24h,
            txns_buys=pair.txns_buys,
            txns_sells=pair.txns_sells,
            buyers=pair.buyers,
            sellers=pair.sellers,
            price_change_m5=pair.price_change_m5,
            price_change_h1=pair.price_change_h1,
            price_change_h24=pair.price_change_h24,
            source=name,
            raw_json=json.dumps(raw_all, default=str),
        )
        session.add(obs)
        return obs

    def collect_token(self, session: Session, mint: str, now: datetime | None = None, eff: Settings | None = None, notifier: Notifier | None = None) -> dict:
        eff = eff or effective_settings(session, self.settings)
        now = now or utcnow()
        results = self._fetch_all(session, mint)
        if not results:
            self._log_quality(session, "no_data", "aucune source n'a retourné de données", mint=mint)
            if notifier:
                notifier.emit("data_unavailable", f"Données indisponibles pour {mint[:12]}…", mint=mint)
            return {"mint": mint, "observations": 0, "tracked": False}
        self._check_coherence(session, mint, results, eff.source_coherence_tolerance_pct)
        primary_name = next((n for n in eff.source_priority if n in results), next(iter(results)))
        primary = results[primary_name]
        market_filter = MarketCapFilter(eff.mcap_threshold_usd, eff.mcap_max_usd)
        market_filter.evaluate(session, primary, now=now)
        token = session.get(Token, mint)
        if token is not None and primary.image_url and not token.logo_url:
            token.logo_url = primary.image_url
        raw_all = {name: {k: v for k, v in vars(pair).items() if k != "raw"} for name, pair in results.items()}
        for name, pair in results.items():
            self._store_observation(session, mint, now, name, pair, raw_all)
        cycles_before = session.scalar(select(func.count(Cycle.id)).where(Cycle.mint == mint)) or 0
        movements_before = session.scalar(select(func.count(Movement.id)).where(Movement.mint == mint, Movement.counted.is_(True))) or 0
        detector, cycles, liquidity, stats = self._analyzers(session, eff)
        detector.process(mint)
        cycles.process(mint)
        liq_event = liquidity.analyze(mint)
        stats.update(mint)
        if notifier:
            cycles_after = session.scalar(select(func.count(Cycle.id)).where(Cycle.mint == mint)) or 0
            movements_after = session.scalar(select(func.count(Movement.id)).where(Movement.mint == mint, Movement.counted.is_(True))) or 0
            if cycles_after > cycles_before:
                new_cycles = session.scalars(select(Cycle).where(Cycle.mint == mint).order_by(Cycle.id.desc()).limit(cycles_after - cycles_before)).all()
                for c in new_cycles:
                    notifier.emit("new_cycle", f"Nouveau cycle #{c.cycle_index} confirmé (hausse {c.up_amplitude_pct:.1f}%, baisse {c.down_amplitude_pct:.1f}%).", mint=mint)
            if movements_after > movements_before:
                new_movs = session.scalars(select(Movement).where(Movement.mint == mint, Movement.counted.is_(True)).order_by(Movement.id.desc()).limit(movements_after - movements_before)).all()
                for m in new_movs:
                    kind = "Hausse" if m.type == "up" else "Baisse"
                    notifier.emit(f"movement_{m.type}", f"{kind} confirmée de {m.amplitude_pct:.1f}% ({m.start_price} → {m.end_price}).", mint=mint)
            if liq_event is not None and liq_event.alert:
                notifier.emit("liquidity_alert", f"Alerte liquidité [{liq_event.alert}]: {liq_event.liquidity_usd} USD.", mint=mint)
        if token is not None and token.created_at is None and self.rpc is not None:
            try:
                created = self.rpc.estimate_creation_ts(mint)
                if created is not None:
                    token.created_at = created
                    token.created_at_source = "solana_rpc_estimate"
            except Exception as exc:
                self._log_quality(session, "rpc_error", str(exc), mint=mint, source="solana_rpc")
        return {"mint": mint, "observations": len(results), "tracked": token.status == "tracked" if token else False, "market_cap": primary.market_cap}

    def analyze_all(self, session: Session, eff: Settings) -> int:
        detector, cycles, liquidity, stats = self._analyzers(session, eff)
        tracked = session.scalars(select(Token).where(Token.status == "tracked")).all()
        for token in tracked:
            detector.process(token.mint)
            cycles.process(token.mint)
            liquidity.analyze(token.mint)
            stats.update(token.mint)
        return len(tracked)

    def collect_once(self) -> dict:
        summary = {"started_at": utcnow().isoformat(), "discovered": 0, "tokens_collected": 0, "tracked": 0, "errors": 0}
        with self.session_factory() as session:
            eff = effective_settings(session, self.settings)
            notifier = Notifier(session)
            try:
                summary["discovered"] = self.discover_candidates(session, eff, notifier)
                session.commit()
            except Exception:
                session.rollback()
                summary["errors"] += 1
                with self.session_factory() as s2:
                    self._log_quality(s2, "discovery_pass_error", traceback.format_exc(limit=3))
                    s2.commit()
            filter_ = MarketCapFilter(eff.mcap_threshold_usd, eff.mcap_max_usd)
            tracked = filter_.list_tracked(session)
            watchlist = filter_.list_watchlist(session)
            cursor = session.get(ScanState, "watchlist_cursor")
            start_index = 0
            if cursor is not None and cursor.value:
                mints = [t.mint for t in watchlist]
                if cursor.value in mints:
                    start_index = (mints.index(cursor.value) + 1) % max(1, len(mints))
            ordered_watchlist = watchlist[start_index:] + watchlist[:start_index] if watchlist else []
            to_poll = tracked + ordered_watchlist[: eff.max_watchlist_per_pass]
            to_poll = to_poll[: eff.max_tokens_watched]
            if ordered_watchlist:
                next_cursor = ordered_watchlist[min(eff.max_watchlist_per_pass, len(ordered_watchlist)) - 1].mint
                if cursor is None:
                    cursor = ScanState(key="watchlist_cursor")
                    session.add(cursor)
                cursor.value = next_cursor
            for token in to_poll:
                try:
                    result = self.collect_token(session, token.mint, eff=eff, notifier=notifier)
                    summary["tokens_collected"] += 1
                    if result.get("tracked"):
                        summary["tracked"] += 1
                    session.commit()
                except Exception:
                    session.rollback()
                    summary["errors"] += 1
                    with self.session_factory() as s2:
                        self._log_quality(s2, "collect_error", f"{token.mint}: {traceback.format_exc(limit=3)}", mint=token.mint)
                        Notifier(s2).emit("connection_error", f"Erreur lors de la collecte de {token.mint[:12]}…", mint=token.mint)
                        s2.commit()
            summary["finished_at"] = utcnow().isoformat()
            state = session.get(ScanState, "last_scan")
            if state is None:
                state = ScanState(key="last_scan")
                session.add(state)
            state.value = json.dumps(summary, default=str)
            status = session.get(ScanState, "scanner_status")
            if status is None:
                status = ScanState(key="scanner_status")
                session.add(status)
            status.value = "running" if summary["errors"] == 0 else "running_with_errors"
            session.commit()
            return summary

    def run_forever(self):
        last_analysis = 0.0
        while True:
            try:
                summary = self.collect_once()
                print(f"[{summary['started_at']}] collected={summary['tokens_collected']} tracked={summary['tracked']} discovered={summary['discovered']} errors={summary['errors']}")
                with self.session_factory() as session:
                    eff = effective_settings(session, self.settings)
                    if eff.analysis_interval_seconds > 0:
                        now_mono = time.monotonic()
                        if now_mono - last_analysis >= eff.analysis_interval_seconds:
                            self.analyze_all(session, eff)
                            session.commit()
                            last_analysis = now_mono
            except KeyboardInterrupt:
                raise
            except Exception:
                traceback.print_exc()
            time.sleep(max(5, self.settings.collect_interval_seconds))
