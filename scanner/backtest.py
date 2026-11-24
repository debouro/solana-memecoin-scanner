import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Cycle, Extreme, Movement, Observation, Simulation, SimulationTrade, Token, utcnow
from .series import primary_source_for

ENTRY_MODES = ("low_confirmation", "up_movement")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def run_backtest(
    session: Session,
    mint: str,
    capital: float = 100.0,
    take_profit_pct: float = 30.0,
    stop_loss_pct: float = 20.0,
    fees_pct: float = 0.5,
    slippage_pct: float = 1.0,
    time_from: datetime | None = None,
    time_to: datetime | None = None,
    max_cycles: int | None = None,
    entry_mode: str = "low_confirmation",
    source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye"),
    store: bool = True,
) -> dict:
    if entry_mode not in ENTRY_MODES:
        raise ValueError(f"entry_mode invalide: {entry_mode}")
    if capital <= 0 or take_profit_pct <= 0 or stop_loss_pct <= 0:
        raise ValueError("capital, take_profit_pct et stop_loss_pct doivent être positifs")
    token = session.get(Token, mint)
    if token is None:
        raise ValueError(f"token inconnu: {mint}")
    source = primary_source_for(session, mint, source_priority)
    stmt = select(Observation).where(Observation.mint == mint)
    if source:
        stmt = stmt.where(Observation.source == source)
    if time_from is not None:
        stmt = stmt.where(Observation.ts >= time_from)
    if time_to is not None:
        stmt = stmt.where(Observation.ts <= time_to)
    stmt = stmt.order_by(Observation.ts.asc(), Observation.id.asc())
    obs = [o for o in session.scalars(stmt).all() if o.price_usd and o.price_usd > 0]
    extremes = list(session.scalars(select(Extreme).where(Extreme.mint == mint, Extreme.confirmed.is_(True)).order_by(Extreme.ts.asc())).all())
    movements = list(session.scalars(select(Movement).where(Movement.mint == mint, Movement.counted.is_(True)).order_by(Movement.start_ts.asc())).all())
    cycles = list(session.scalars(select(Cycle).where(Cycle.mint == mint, Cycle.status == "confirmed").order_by(Cycle.start_ts.asc())).all())

    config = {
        "mint": mint,
        "capital": capital,
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": stop_loss_pct,
        "fees_pct": fees_pct,
        "slippage_pct": slippage_pct,
        "time_from": time_from.isoformat() if time_from else None,
        "time_to": time_to.isoformat() if time_to else None,
        "max_cycles": max_cycles,
        "entry_mode": entry_mode,
        "source": source,
    }

    if len(obs) < 2:
        result = {"config": config, "insufficient_data": True, "note": "Moins de 2 observations de prix dans la période analysée.", "trades": [], "summary": None}
        if store:
            sim = Simulation(mint=mint, config_json=json.dumps(config, default=str), results_json=json.dumps(result, default=str), insufficient_data=True, note=result["note"])
            session.add(sim)
        return result

    signal_extremes = []
    if entry_mode == "low_confirmation":
        signal_extremes = [e for e in extremes if e.kind == "low" and e.confirmed_at is not None]
    else:
        lows = {m.from_extreme_id: m for m in movements if m.type == "up"}
        signal_extremes = [e for e in extremes if e.id in lows and e.confirmed_at is not None]

    trades: list[dict] = []
    consumed_signals: set[int] = set()
    position = None
    cycles_used = 0

    def cycle_for(ts: datetime):
        for c in cycles:
            if c.start_ts and c.end_ts and _as_utc(c.start_ts) <= ts <= _as_utc(c.end_ts):
                return c.id
        return None

    for o in obs:
        ts = _as_utc(o.ts)
        price = o.price_usd
        if position is None:
            for e in signal_extremes:
                if e.id in consumed_signals:
                    continue
                if _as_utc(e.confirmed_at) <= ts:
                    consumed_signals.add(e.id)
                    entry_adj = price * (1 + slippage_pct / 100.0)
                    qty = capital / (entry_adj * (1 + fees_pct / 100.0))
                    position = {"entry_ts": ts, "entry_price": entry_adj, "qty": qty, "raw_entry": price, "extreme_id": e.id, "signal": entry_mode}
                    if max_cycles is not None and cycles_used >= max_cycles:
                        position = None
                        consumed_signals.discard(e.id)
                    break
        else:
            exit_price = None
            status = None
            tp_price = position["entry_price"] * (1 + take_profit_pct / 100.0)
            sl_price = position["entry_price"] * (1 - stop_loss_pct / 100.0)
            if price >= tp_price:
                exit_price = price * (1 - slippage_pct / 100.0)
                status = "take_profit"
            elif price <= sl_price:
                exit_price = price * (1 - slippage_pct / 100.0)
                status = "stop_loss"
            if exit_price is not None:
                proceeds = position["qty"] * exit_price * (1 - fees_pct / 100.0)
                net_amount = proceeds - capital
                net_pct = net_amount / capital * 100.0
                gross_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100.0
                fees_usd = capital * fees_pct / 100.0 + proceeds * fees_pct / 100.0
                slippage_usd = position["qty"] * position["raw_entry"] * slippage_pct / 100.0 * 2
                trade = {
                    "entry_ts": position["entry_ts"],
                    "entry_price": position["entry_price"],
                    "raw_entry_price": position["raw_entry"],
                    "exit_ts": ts,
                    "exit_price": exit_price,
                    "gross_pct": gross_pct,
                    "fees_usd": fees_usd,
                    "slippage_usd": slippage_usd,
                    "net_pct": net_pct,
                    "net_amount": net_amount,
                    "status": status,
                    "entry_signal": position["signal"],
                    "extreme_id": position["extreme_id"],
                    "cycle_id": cycle_for(position["entry_ts"]),
                }
                trades.append(trade)
                if trade["cycle_id"]:
                    cycles_used += 1
                position = None

    if position is not None:
        last = obs[-1]
        exit_price = last.price_usd * (1 - slippage_pct / 100.0)
        proceeds = position["qty"] * exit_price * (1 - fees_pct / 100.0)
        net_amount = proceeds - capital
        net_pct = net_amount / capital * 100.0
        gross_pct = (exit_price - position["entry_price"]) / position["entry_price"] * 100.0
        fees_usd = capital * fees_pct / 100.0 + proceeds * fees_pct / 100.0
        slippage_usd = position["qty"] * position["raw_entry"] * slippage_pct / 100.0 * 2
        trades.append({
            "entry_ts": position["entry_ts"], "entry_price": position["entry_price"], "raw_entry_price": position["raw_entry"],
            "exit_ts": _as_utc(last.ts), "exit_price": exit_price, "gross_pct": gross_pct, "fees_usd": fees_usd,
            "slippage_usd": slippage_usd, "net_pct": net_pct, "net_amount": net_amount,
            "status": "end_of_period", "entry_signal": position["signal"], "extreme_id": position["extreme_id"], "cycle_id": cycle_for(position["entry_ts"]),
        })

    nets = [t["net_pct"] for t in trades]
    wins = [t for t in trades if t["net_amount"] > 0]
    losses = [t for t in trades if t["net_amount"] <= 0]
    summary = {
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": (len(wins) / len(trades) * 100.0) if trades else None,
        "avg_win_pct": (sum(t["net_pct"] for t in wins) / len(wins)) if wins else None,
        "avg_loss_pct": (sum(t["net_pct"] for t in losses) / len(losses)) if losses else None,
        "net_total_amount": sum(t["net_amount"] for t in trades),
        "net_avg_per_trade": (sum(t["net_amount"] for t in trades) / len(trades)) if trades else None,
        "best_trade_pct": max(nets) if nets else None,
        "worst_trade_pct": min(nets) if nets else None,
        "total_fees_usd": sum(t["fees_usd"] for t in trades),
        "total_slippage_usd": sum(t["slippage_usd"] for t in trades),
        "final_capital": capital + sum(t["net_amount"] for t in trades),
        "observations_used": len(obs),
        "period_from": _as_utc(obs[0].ts).isoformat(),
        "period_to": _as_utc(obs[-1].ts).isoformat(),
    }
    result = {
        "config": config,
        "insufficient_data": len(trades) == 0,
        "note": None if trades else "Aucune opportunité d'entrée ne correspond aux critères sur la période (données insuffisantes pour simuler).",
        "summary": summary,
        "trades": trades,
    }
    sim_id = None
    if store:
        sim = Simulation(mint=mint, config_json=json.dumps(config, default=str), results_json=json.dumps(result, default=str), insufficient_data=result["insufficient_data"], note=result["note"])
        session.add(sim)
        session.flush()
        sim_id = sim.id
        for t in trades:
            session.add(SimulationTrade(
                simulation_id=sim.id, mint=mint,
                entry_ts=t["entry_ts"], entry_price=t["entry_price"],
                exit_ts=t["exit_ts"], exit_price=t["exit_price"],
                gross_pct=t["gross_pct"], fees_usd=t["fees_usd"], slippage_usd=t["slippage_usd"],
                net_pct=t["net_pct"], net_amount=t["net_amount"], status=t["status"],
                entry_signal=t["entry_signal"], extreme_id=t["extreme_id"], cycle_id=t["cycle_id"],
            ))
    result["simulation_id"] = sim_id
    return result
