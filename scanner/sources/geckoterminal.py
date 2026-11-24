from .base import BaseSource, DiscoveredToken, HttpClient, PairData, iso_to_dt, to_float, to_int


def _base_mint(pool: dict) -> str | None:
    rel = (pool.get("relationships") or {}).get("base_token") or {}
    data = rel.get("data") or {}
    ident = data.get("id") or ""
    if ident.startswith("solana_"):
        return ident[len("solana_"):]
    return ident or None


def _pool_dex(pool: dict) -> str | None:
    rel = (pool.get("relationships") or {}).get("dex") or {}
    return (rel.get("data") or {}).get("id")


class GeckoTerminalSource(BaseSource):
    name = "geckoterminal"

    def __init__(self, http: HttpClient, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")

    def _token_meta(self, mint: str) -> tuple[str | None, str | None, str | None]:
        data = self.http.get(f"{self.base_url}/networks/solana/tokens/{mint}")
        if not isinstance(data, dict):
            return None, None, None
        attrs = (data.get("data") or {}).get("attributes") or {}
        return attrs.get("name"), attrs.get("symbol"), attrs.get("image_url")

    def discover(self, pages: int = 3) -> list[DiscoveredToken]:
        found: dict[str, DiscoveredToken] = {}
        for path in ("trending_pools", "new_pools"):
            for page in range(1, pages + 1):
                data = self.http.get(f"{self.base_url}/networks/solana/{path}", params={"page": page})
                if not isinstance(data, dict):
                    continue
                for pool in data.get("data") or []:
                    if not isinstance(pool, dict):
                        continue
                    attrs = pool.get("attributes") or {}
                    address = _base_mint(pool)
                    if not address:
                        continue
                    pool_name = attrs.get("name") or ""
                    symbol_guess = pool_name.split(" / ")[0].strip() if " / " in pool_name else None
                    if address not in found:
                        found[address] = DiscoveredToken(
                            mint=address,
                            name=None,
                            symbol=symbol_guess,
                            pair_created_at=iso_to_dt(attrs.get("pool_created_at")),
                            source=self.name,
                        )
        return list(found.values())

    def fetch_token(self, mint: str) -> PairData | None:
        data = self.http.get(f"{self.base_url}/networks/solana/tokens/{mint}/pools")
        if not isinstance(data, dict):
            return None
        pools = [p for p in (data.get("data") or []) if isinstance(p, dict)]
        if not pools:
            return None
        best = max(pools, key=lambda p: to_float((p.get("attributes") or {}).get("reserve_in_usd")) or 0.0)
        attrs = best.get("attributes") or {}
        name, symbol, image_url = self._token_meta(mint)
        volume = attrs.get("volume_usd") or {}
        txns = (attrs.get("transactions") or {}).get("h24") or {}
        price_change = attrs.get("price_change_percentage") or {}
        return PairData(
            mint=mint,
            name=name,
            symbol=symbol,
            price_usd=to_float(attrs.get("base_token_price_usd") or attrs.get("token_price_usd")),
            market_cap=to_float(attrs.get("market_cap_usd")),
            fdv=to_float(attrs.get("fdv_usd")),
            liquidity_usd=to_float(attrs.get("reserve_in_usd")),
            volume_24h=to_float(volume.get("h24")),
            txns_buys=to_int(txns.get("buys")),
            txns_sells=to_int(txns.get("sells")),
            buyers=to_int(txns.get("buyers")),
            sellers=to_int(txns.get("sellers")),
            price_change_m5=to_float(price_change.get("m5")),
            price_change_h1=to_float(price_change.get("h1")),
            price_change_h24=to_float(price_change.get("h24")),
            image_url=image_url,
            pair_created_at=iso_to_dt(attrs.get("pool_created_at")),
            dex=_pool_dex(best),
            pair_address=attrs.get("address"),
            raw=attrs,
        )

    def fetch_ohlcv(self, pool_address: str, time_from: int, time_to: int, aggregate: int = 1) -> list[dict]:
        data = self.http.get(
            f"{self.base_url}/networks/solana/pools/{pool_address}/ohlcv/minute",
            params={"aggregate": aggregate, "currency": "usd", "time_from": time_from, "time_to": time_to},
        )
        if not isinstance(data, dict):
            return []
        attrs = (data.get("data") or {}).get("attributes") or {}
        items = attrs.get("ohlcv_list") or []
        result = []
        for row in items:
            if not isinstance(row, list) or len(row) < 6:
                continue
            from .base import epoch_s_to_dt
            result.append({"ts": epoch_s_to_dt(row[0]), "open": to_float(row[1]), "high": to_float(row[2]), "low": to_float(row[3]), "close": to_float(row[4]), "volume": to_float(row[5])})
        return [r for r in result if r["ts"] is not None and r["close"] is not None]
