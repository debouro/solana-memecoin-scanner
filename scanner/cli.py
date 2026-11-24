import argparse
import sys
from datetime import datetime

from sqlalchemy import select

from .config import get_settings
from .models import Cycle, DataQuality, LiquidityEvent, Movement, Observation, Token, TokenStats
from .runner import build_components, run_scan_once, serve


def _fmt_ts(ts) -> str:
    return ts.isoformat() if isinstance(ts, datetime) else str(ts)


def cmd_init_db(args):
    settings, session_factory, _, _ = build_components()
    print(f"Base initialisée: {settings.database_url}")


def cmd_add_token(args):
    settings, session_factory, _, collector = build_components()
    with session_factory() as session:
        token = collector.add_token(session, args.mint)
        session.commit()
        print(f"Token ajouté à la watchlist: {token.mint}")


def cmd_scan(args):
    summary = run_scan_once()
    print(summary)


def cmd_serve(args):
    serve()


def cmd_report(args):
    settings, session_factory, _, _ = build_components()
    with session_factory() as session:
        tokens = list(session.scalars(select(Token).where(Token.status == "tracked").order_by(Token.mint)).all())
        if args.mint:
            tokens = [t for t in tokens if t.mint == args.mint]
        if not tokens:
            print("Aucun token suivi (status=tracked). Lancez d'abord: python -m scanner.cli scan")
            return 0
        for token in tokens:
            print("=" * 80)
            print(f"{token.symbol or '?'} ({token.name or '?'})")
            print(f"  mint: {token.mint}")
            print(f"  créé le: {_fmt_ts(token.created_at)} (source: {token.created_at_source})")
            print(f"  1er franchissement {token.threshold_usd:.0f}$: {_fmt_ts(token.first_crossed_threshold_at)}")
            print(f"  market cap max observée: {token.max_market_cap}")
            stats = session.get(TokenStats, token.mint)
            if stats:
                print(f"  cycles: total={stats.total_cycles} confirmés={stats.confirmed_cycles} "
                      f"hausse moy={stats.avg_up_pct} baisse moy={stats.avg_down_pct} "
                      f"durée moy={stats.avg_cycle_duration_s}s liquidité={stats.last_liquidity_usd} (tendance: {stats.liquidity_trend})")
            cycles = list(session.scalars(select(Cycle).where(Cycle.mint == token.mint).order_by(Cycle.cycle_index)).all())
            for c in cycles[-5:]:
                print(f"  cycle #{c.cycle_index}: start={c.start_price} min={c.min_price} max={c.max_price} "
                      f"up={c.up_amplitude_pct:.2f}% down={c.down_amplitude_pct:.2f}% "
                      f"low@{_fmt_ts(c.low_ts)} high@{_fmt_ts(c.high_ts)} liq(low)={c.liquidity_at_low} liq(high)={c.liquidity_at_high}")
            movements = list(session.scalars(select(Movement).where(Movement.mint == token.mint, Movement.counted.is_(True)).order_by(Movement.id)).all())
            for m in movements[-5:]:
                print(f"  mouvement {m.type} compté: {m.amplitude_pct:.2f}% ({m.start_price} -> {m.end_price}) {_fmt_ts(m.start_ts)} -> {_fmt_ts(m.end_ts)}")
            alerts = list(session.scalars(select(LiquidityEvent).where(LiquidityEvent.mint == token.mint, LiquidityEvent.alert.isnot(None)).order_by(LiquidityEvent.ts.desc()).limit(5)).all())
            for a in alerts:
                print(f"  ALERTE liquidité [{a.alert}]: {a.liquidity_usd} USD à {_fmt_ts(a.ts)} (delta {a.delta_pct}%)")
            quality = list(session.scalars(select(DataQuality).where(DataQuality.mint == token.mint).order_by(DataQuality.ts.desc()).limit(5)).all())
            for q in quality:
                print(f"  data-quality [{q.issue}] ({q.source}): {q.detail}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="scanner", description="Scanner de memecoins Solana (market cap >= seuil, variations >= 35%, cycles, liquidité)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Initialiser la base de données").set_defaults(func=cmd_init_db)
    p_add = sub.add_parser("add-token", help="Ajouter un mint à la watchlist manuellement")
    p_add.add_argument("mint")
    p_add.set_defaults(func=cmd_add_token)
    sub.add_parser("scan", help="Exécuter un passage complet (découverte + collecte + analyse)").set_defaults(func=cmd_scan)
    sub.add_parser("serve", help="Lancer la collecte périodique + l'API interne").set_defaults(func=cmd_serve)
    p_rep = sub.add_parser("report", help="Rapport console des tokens suivis")
    p_rep.add_argument("--mint", default=None)
    p_rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
