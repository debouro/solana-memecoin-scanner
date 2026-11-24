from ..config import Settings
from .base import BaseSource, DiscoveredToken, HttpClient, PairData, RateLimiter
from .birdeye import BirdeyeSource
from .dexscreener import DexScreenerSource
from .geckoterminal import GeckoTerminalSource
from .solana_rpc import SolanaRpcSource


def build_sources(settings: Settings) -> dict[str, BaseSource]:
    sources: dict[str, BaseSource] = {}
    ds_http = HttpClient(settings.request_timeout_seconds, settings.max_retries, RateLimiter(settings.rate_limit_per_minute))
    sources["dexscreener"] = DexScreenerSource(ds_http, settings.dexscreener_base_url)
    gt_http = HttpClient(settings.request_timeout_seconds, settings.max_retries, RateLimiter(settings.rate_limit_per_minute))
    sources["geckoterminal"] = GeckoTerminalSource(gt_http, settings.geckoterminal_base_url)
    if settings.birdeye_api_key:
        be_http = HttpClient(settings.request_timeout_seconds, settings.max_retries, RateLimiter(30))
        sources["birdeye"] = BirdeyeSource(be_http, settings.birdeye_base_url, settings.birdeye_api_key)
    return sources


def build_rpc(settings: Settings) -> SolanaRpcSource | None:
    if not settings.use_solana_rpc:
        return None
    http = HttpClient(settings.request_timeout_seconds, settings.max_retries, RateLimiter(10))
    return SolanaRpcSource(http, settings.solana_rpc_url)
