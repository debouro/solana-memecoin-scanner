import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests


@dataclass
class PairData:
    mint: str
    chain: str = "solana"
    name: str | None = None
    symbol: str | None = None
    price_usd: float | None = None
    market_cap: float | None = None
    fdv: float | None = None
    liquidity_usd: float | None = None
    volume_24h: float | None = None
    txns_buys: int | None = None
    txns_sells: int | None = None
    buyers: int | None = None
    sellers: int | None = None
    price_change_m5: float | None = None
    price_change_h1: float | None = None
    price_change_h24: float | None = None
    image_url: str | None = None
    pair_created_at: datetime | None = None
    dex: str | None = None
    pair_address: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class DiscoveredToken:
    mint: str
    name: str | None = None
    symbol: str | None = None
    pair_created_at: datetime | None = None
    source: str = ""


class RateLimiter:
    def __init__(self, per_minute: int):
        self.interval = 60.0 / per_minute if per_minute and per_minute > 0 else 0.0
        self._last = 0.0

    def wait(self):
        if self.interval <= 0:
            return
        now = time.monotonic()
        delta = now - self._last
        if delta < self.interval:
            time.sleep(self.interval - delta)
        self._last = time.monotonic()


class HttpClient:
    def __init__(self, timeout: int, max_retries: int, rate_limiter: RateLimiter | None = None, session: requests.Session | None = None):
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.limiter = rate_limiter or RateLimiter(0)
        self.session = session or requests.Session()

    def get(self, url: str, params: dict | None = None, headers: dict | None = None):
        attempt = 0
        backoff = 2.0
        while True:
            self.limiter.wait()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            except requests.RequestException:
                attempt += 1
                if attempt >= self.max_retries:
                    return None
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                attempt += 1
                if attempt >= self.max_retries:
                    return None
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                return None
            try:
                return resp.json()
            except ValueError:
                return None

    def post(self, url: str, payload: dict, headers: dict | None = None):
        attempt = 0
        backoff = 2.0
        while True:
            self.limiter.wait()
            try:
                resp = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            except requests.RequestException:
                attempt += 1
                if attempt >= self.max_retries:
                    return None
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                attempt += 1
                if attempt >= self.max_retries:
                    return None
                time.sleep(backoff)
                backoff *= 2
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                return None
            try:
                return resp.json()
            except ValueError:
                return None


class BaseSource:
    name = "base"
    chain = "solana"

    def fetch_token(self, mint: str) -> PairData | None:
        raise NotImplementedError

    def discover(self, pages: int = 3) -> list[DiscoveredToken]:
        raise NotImplementedError


def epoch_ms_to_dt(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def epoch_s_to_dt(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def iso_to_dt(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_float(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def to_int(value) -> int | None:
    f = to_float(value)
    return int(f) if f is not None else None
