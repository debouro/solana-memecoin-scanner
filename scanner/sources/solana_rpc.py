from datetime import datetime, timezone

from .base import HttpClient, epoch_s_to_dt, to_float


class SolanaRpcSource:
    name = "solana_rpc"
    chain = "solana"

    def __init__(self, http: HttpClient, rpc_url: str):
        self.http = http
        self.rpc_url = rpc_url

    def _call(self, method: str, params: list):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        data = self.http.post(self.rpc_url, payload)
        if not isinstance(data, dict):
            return None
        return data.get("result")

    def estimate_creation_ts(self, mint: str) -> datetime | None:
        result = self._call("getSignaturesForAddress", [mint, {"limit": 1000}])
        if not isinstance(result, list) or not result:
            return None
        times = [epoch_s_to_dt(item.get("blockTime")) for item in result if isinstance(item, dict)]
        times = [t for t in times if t is not None]
        if not times:
            return None
        return min(times)

    def token_supply(self, mint: str) -> float | None:
        result = self._call("getTokenSupply", [mint])
        if not isinstance(result, dict):
            return None
        value = (result.get("value") or {}).get("amount")
        return to_float(value)

    def account_exists(self, mint: str) -> bool:
        result = self._call("getAccountInfo", [mint, {"encoding": "base64"}])
        return isinstance(result, dict) and result.get("value") is not None


def utc_ts(dt: datetime) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp()) if dt.tzinfo is None else int(dt.timestamp())
