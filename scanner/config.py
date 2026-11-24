import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return int(raw)




def _env_float_opt(name: str, default: float | None) -> float | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return float(raw)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw


@dataclass
class Settings:
    database_url: str = _env_str("DATABASE_URL", "sqlite:///scanner.db")
    mcap_threshold_usd: float = _env_float("MCAP_THRESHOLD_USD", 50000.0)
    variation_threshold_pct: float = _env_float("VARIATION_THRESHOLD_PCT", 35.0)
    collect_interval_seconds: int = _env_int("COLLECT_INTERVAL_SECONDS", 60)
    confirmation_window: int = _env_int("CONFIRMATION_WINDOW", 3)
    retracement_pct: float = _env_float("RETRACEMENT_PCT", 5.0)
    liquidity_low_usd: float = _env_float("LIQUIDITY_LOW_USD", 10000.0)
    liquidity_decline_pct: float = _env_float("LIQUIDITY_DECLINE_PCT", 30.0)
    liquidity_decline_window: int = _env_int("LIQUIDITY_DECLINE_WINDOW", 10)
    source_priority: tuple = ("dexscreener", "geckoterminal", "birdeye")
    source_coherence_tolerance_pct: float = _env_float("SOURCE_COHERENCE_TOLERANCE_PCT", 20.0)
    dexscreener_base_url: str = _env_str("DEXSCREENER_BASE_URL", "https://api.dexscreener.com")
    geckoterminal_base_url: str = _env_str("GECKOTERMINAL_BASE_URL", "https://api.geckoterminal.com/api/v2")
    birdeye_base_url: str = _env_str("BIRDEYE_BASE_URL", "https://public-api.birdeye.so")
    birdeye_api_key: str | None = os.getenv("BIRDEYE_API_KEY") or None
    solana_rpc_url: str = _env_str("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    use_solana_rpc: bool = _env_str("USE_SOLANA_RPC", "0") == "1"
    request_timeout_seconds: int = _env_int("REQUEST_TIMEOUT_SECONDS", 15)
    max_retries: int = _env_int("MAX_RETRIES", 3)
    rate_limit_per_minute: int = _env_int("RATE_LIMIT_PER_MINUTE", 55)
    discovery_pages: int = _env_int("DISCOVERY_PAGES", 3)
    max_watchlist_per_pass: int = _env_int("MAX_WATCHLIST_PER_PASS", 50)
    api_host: str = _env_str("API_HOST", "127.0.0.1")
    api_port: int = _env_int("API_PORT", 8000)
    mcap_max_usd: float | None = _env_float_opt("MCAP_MAX_USD", None)
    up_threshold_pct: float | None = _env_float_opt("UP_THRESHOLD_PCT", None)
    down_threshold_pct: float | None = _env_float_opt("DOWN_THRESHOLD_PCT", None)
    min_up_duration_s: float | None = _env_float_opt("MIN_UP_DURATION_S", None)
    max_up_duration_s: float | None = _env_float_opt("MAX_UP_DURATION_S", None)
    min_down_duration_s: float | None = _env_float_opt("MIN_DOWN_DURATION_S", None)
    max_down_duration_s: float | None = _env_float_opt("MAX_DOWN_DURATION_S", None)
    min_cycle_duration_s: float | None = _env_float_opt("MIN_CYCLE_DURATION_S", None)
    max_cycle_duration_s: float | None = _env_float_opt("MAX_CYCLE_DURATION_S", None)
    min_liquidity_usd: float = _env_float("MIN_LIQUIDITY_USD", 0.0)
    min_volume_24h_usd: float = _env_float("MIN_VOLUME_24H_USD", 0.0)
    max_liquidity_change_pct: float | None = _env_float_opt("MAX_LIQUIDITY_CHANGE_PCT", None)
    refresh_interval_seconds: int = _env_int("REFRESH_INTERVAL_SECONDS", 15)
    analysis_interval_seconds: int = _env_int("ANALYSIS_INTERVAL_SECONDS", 0)
    max_tokens_watched: int = _env_int("MAX_TOKENS_WATCHED", 500)
    api_only: bool = _env_str("API_ONLY", "0") == "1"

    def public_dict(self) -> dict:
        data = {
            "database_url": self.database_url.split("///")[-1] if "sqlite" in self.database_url else "external",
            "mcap_threshold_usd": self.mcap_threshold_usd,
            "variation_threshold_pct": self.variation_threshold_pct,
            "collect_interval_seconds": self.collect_interval_seconds,
            "confirmation_window": self.confirmation_window,
            "retracement_pct": self.retracement_pct,
            "liquidity_low_usd": self.liquidity_low_usd,
            "liquidity_decline_pct": self.liquidity_decline_pct,
            "liquidity_decline_window": self.liquidity_decline_window,
            "source_priority": list(self.source_priority),
            "source_coherence_tolerance_pct": self.source_coherence_tolerance_pct,
            "birdeye_api_key_configured": bool(self.birdeye_api_key),
            "use_solana_rpc": self.use_solana_rpc,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "discovery_pages": self.discovery_pages,
            "max_watchlist_per_pass": self.max_watchlist_per_pass,
            "api_host": self.api_host,
            "api_port": self.api_port,
            "mcap_max_usd": self.mcap_max_usd,
            "up_threshold_pct": self.up_threshold_pct,
            "down_threshold_pct": self.down_threshold_pct,
            "min_up_duration_s": self.min_up_duration_s,
            "max_up_duration_s": self.max_up_duration_s,
            "min_down_duration_s": self.min_down_duration_s,
            "max_down_duration_s": self.max_down_duration_s,
            "min_cycle_duration_s": self.min_cycle_duration_s,
            "max_cycle_duration_s": self.max_cycle_duration_s,
            "min_liquidity_usd": self.min_liquidity_usd,
            "min_volume_24h_usd": self.min_volume_24h_usd,
            "max_liquidity_change_pct": self.max_liquidity_change_pct,
            "refresh_interval_seconds": self.refresh_interval_seconds,
            "analysis_interval_seconds": self.analysis_interval_seconds,
            "max_tokens_watched": self.max_tokens_watched,
        }
        return data


def get_settings() -> Settings:
    return Settings()
