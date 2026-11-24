from .base import BaseSource, DiscoveredToken, HttpClient, PairData, epoch_ms_to_dt, to_float, to_int


class DexScreenerSource(BaseSource):
    name = "dexscreener"

    def __init__(self, http: HttpClient, base_url: str):
        self.http = http
        self.base_url = base_url.rstrip("/")

    def fetch_token(self, mint: str) -> PairData | None:
        data = self.http.get(f"{self.base_url}/latest/dex/tokens/{mint}")
        if not isinstance(data, dict):
            return None
        pairs = data.get("pairs") or []
        solana_pairs = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"]
        if not solana_pairs:
            return None
        best = max(solana_pairs, key=lambda p: to_float((p.get("liquidity") or {}).get("usd")) or 0.0)
        base_token = best.get("baseToken") or {}
        liquidity = best.get("liquidity") or {}
        txns = (best.get("txns") or {}).get("h24") or {}
        volume = best.get("volume") or {}
        price_change = best.get("priceChange") or {}
        info = best.get("info") or {}
        return PairData(
            mint=mint,
            name=base_token.get("name"),
            symbol=base_token.get("symbol"),
            price_usd=to_float(best.get("priceUsd")),
            market_cap=to_float(best.get("marketCap")),
            fdv=to_float(best.get("fdv")),
            liquidity_usd=to_float(liquidity.get("usd")),
            volume_24h=to_float(volume.get("h24")),
            txns_buys=to_int(txns.get("buys")),
            txns_sells=to_int(txns.get("sells")),
            price_change_m5=to_float(price_change.get("m5")),
            price_change_h1=to_float(price_change.get("h1")),
            price_change_h24=to_float(price_change.get("h24")),
            image_url=info.get("imageUrl"),
            pair_created_at=epoch_ms_to_dt(best.get("pairCreatedAt")),
            dex=best.get("dexId"),
            pair_address=best.get("pairAddress"),
            raw=best,
        )

    def discover(self, pages: int = 3) -> list[DiscoveredToken]:
        found: dict[str, DiscoveredToken] = {}
        endpoints = ("/token-boosts/top/v1", "/token-boosts/latest/v1", "/token-profiles/latest/v1")
        for endpoint in endpoints:
            data = self.http.get(f"{self.base_url}{endpoint}")
            items: list = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("tokens") or data.get("profiles") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("chainId") not in (None, "solana"):
                    continue
                address = item.get("tokenAddress") or item.get("address")
                if not address:
                    continue
                if address not in found:
                    found[address] = DiscoveredToken(
                        mint=address,
                        name=item.get("name"),
                        symbol=item.get("symbol"),
                        pair_created_at=epoch_ms_to_dt(item.get("pairCreatedAt") or item.get("createdAt")),
                        source=self.name,
                    )
        return list(found.values())
