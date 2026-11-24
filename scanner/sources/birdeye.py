from .base import BaseSource, DiscoveredToken, HttpClient, PairData, epoch_s_to_dt, to_float, to_int


class BirdeyeSource(BaseSource):
    name = "birdeye"

    def __init__(self, http: HttpClient, base_url: str, api_key: str):
        if not api_key:
            raise ValueError("BIRDEYE_API_KEY requis pour la source birdeye")
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-KEY": api_key, "x-chain": "solana", "accept": "application/json"}

    def _pick(self, data: dict, *keys: str) -> float | None:
        for key in keys:
            value = to_float(data.get(key))
            if value is not None:
                return value
        return None

    def fetch_token(self, mint: str) -> PairData | None:
        market = self.http.get(f"{self.base_url}/defi/v3/solana/token/market-data", params={"address": mint}, headers=self.headers)
        data = (market or {}).get("data") if isinstance(market, dict) else None
        if not isinstance(data, dict):
            return None
        price = self._pick(data, "price", "price_usd")
        liquidity = self._pick(data, "liquidity", "liquidity_usd")
        market_cap = self._pick(data, "market_cap", "mc", "marketCap")
        fdv = self._pick(data, "fdv", "fdv_usd")
        volume = self._pick(data, "v24hUSD", "volume_24h_usd", "volume24hUSD")
        txns = data.get("number_of_transactions_24h") or data.get("txns_24h")
        return PairData(
            mint=mint,
            name=data.get("name"),
            symbol=data.get("symbol"),
            price_usd=price,
            market_cap=market_cap,
            fdv=fdv,
            liquidity_usd=liquidity,
            volume_24h=volume,
            txns_buys=to_int((txns or {}).get("buys")) if isinstance(txns, dict) else None,
            txns_sells=to_int((txns or {}).get("sells")) if isinstance(txns, dict) else None,
            pair_created_at=epoch_s_to_dt(data.get("created_at") or data.get("createdAt")),
            dex="birdeye-aggregated",
            raw=data,
        )

    def fetch_ohlcv(self, mint: str, time_from: int, time_to: int, timeframe: str = "1m") -> list[dict]:
        data = self.http.get(
            f"{self.base_url}/defi/v3/ohlcv",
            params={"address": mint, "type": timeframe, "time_from": time_from, "time_to": time_to},
            headers=self.headers,
        )
        items = ((data or {}).get("data") or {}).get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        result = []
        for row in items:
            if not isinstance(row, dict):
                continue
            result.append({"ts": epoch_s_to_dt(row.get("unixTime") or row.get("time")), "close": to_float(row.get("c") or row.get("close")), "volume": to_float(row.get("v") or row.get("volume"))})
        return [r for r in result if r["ts"] is not None and r["close"] is not None]

    def discover(self, pages: int = 3) -> list[DiscoveredToken]:
        data = self.http.get(f"{self.base_url}/defi/v3/solana/token/trending", headers=self.headers)
        items = (data or {}).get("data") or {} if isinstance(data, dict) else {}
        tokens = items.get("tokens") if isinstance(items, dict) else items
        found: list[DiscoveredToken] = []
        for item in tokens or []:
            address = item.get("address")
            if not address:
                continue
            found.append(DiscoveredToken(mint=address, name=item.get("name"), symbol=item.get("symbol"), pair_created_at=epoch_s_to_dt(item.get("created_at")), source=self.name))
        return found
