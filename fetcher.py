"""Polite HTTP fetcher: robots.txt, per-domain delay + jitter, retries.

Edit USER_AGENT / DEFAULT_DELAY / MAX_RETRIES below to change behaviour.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger("scrape")

# --- settings --------------------------------------------------------------
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Full browser-like headers: Cloudflare 403s requests that lack sec-fetch-*/sec-ch-ua*.
BROWSER_HEADERS: dict[str, str] = {
    "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Upgrade-Insecure-Requests": "1",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
        "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "sec-fetch-site": "none",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "Accept-Language": "en-US,en;q=0.9",
    "Priority": "u=0, i",
}
DEFAULT_DELAY: float = 3.0        # seconds between requests to same domain
DELAY_JITTER: float = 1.0         # extra random 0..JITTER seconds
MAX_RETRIES: int = 3
BACKOFF_BASE: float = 2.0         # 2s, 4s, 8s ...
TIMEOUT: float = 30.0
OBEY_ROBOTS: bool = True
# 401/403 = often a temporary anti-bot wall: cool down and retry a few times,
# and only stop the domain after that (multi-day runs must survive short blocks).
BLOCKING_STATUS: tuple[int, ...] = (401, 403)
MAX_BLOCK_RETRIES: int = 3
BLOCK_COOLDOWN_BASE: float = 60.0   # 60s, 120s, 240s ...
BLOCK_COOLDOWN_MAX: float = 900.0   # cap per cooldown
# 429 = rate limit: honour Retry-After / cool down politely, then stop the domain.
# Multi-day runs must ride out long rate-limit stretches, so the patience is generous:
# 60+120+240+480+960+1800s (~1.2 h) before a pass gives up on a domain.
MAX_RATE_RETRIES: int = 6
RATE_COOLDOWN_BASE: float = 60.0  # 60s, 120s, 240s ...
RATE_COOLDOWN_MAX: float = 1800.0  # cap for server-provided Retry-After


class BlockedError(RuntimeError):
    """Site said stop (403/429/CAPTCHA) -- abandon this domain."""


class RobotsDisallowed(RuntimeError):
    """robots.txt forbids this URL."""


class FetchError(RuntimeError):
    """Non-blocking failure (404, 5xx after retries, network error)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    html: str


class Fetcher:
    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        user_agent: str = USER_AGENT,
        timeout: float = TIMEOUT,
        obey_robots: bool = OBEY_ROBOTS,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.obey_robots = obey_robots
        self.blocked_domains: set[str] = set()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": user_agent})
        self._session.headers.update(BROWSER_HEADERS)
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}

    # --- politeness --------------------------------------------------------
    def _throttle(self, domain: str) -> None:
        wait = self.delay + random.uniform(0, DELAY_JITTER)
        last = self._last_request.get(domain)
        if last is not None:
            remaining = wait - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request[domain] = time.monotonic()

    def _robots_allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            self._robots[root] = self._load_robots(root)
        rp = self._robots[root]
        return True if rp is None else rp.can_fetch(self._session.headers["User-Agent"], url)

    def _load_robots(self, root: str) -> RobotFileParser | None:
        rp = RobotFileParser()
        try:
            resp = self._session.get(f"{root}/robots.txt", timeout=self.timeout)
            if resp.status_code in (401, 403):
                log.warning("robots.txt locked (%s) -> treating as disallow", root)
                rp.parse(["User-agent: *", "Disallow: /"])
            elif resp.status_code in (404, 410) or resp.status_code >= 500:
                rp.parse([])  # missing/broken robots -> allow
            else:
                rp.parse(resp.text.splitlines())
        except requests.RequestException as exc:
            log.warning("robots.txt fetch failed for %s (%s) -> allowing", root, exc)
            rp.parse([])
        return rp

    # --- fetching ----------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        domain = urlparse(url).netloc
        if domain in self.blocked_domains:
            raise BlockedError(f"domain already blocked: {domain}")
        if not self._robots_allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        attempt = 0
        rate_hits = 0
        block_hits = 0
        while True:
            self._throttle(domain)
            try:
                resp = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    raise FetchError(f"giving up on {url}: {exc}") from exc
                log.warning("attempt %d/%d network error %s: %s", attempt, MAX_RETRIES, url, exc)
                time.sleep(BACKOFF_BASE**attempt)
                continue

            if resp.status_code == 429:
                # rate limited: honour Retry-After (or back off), then stop the domain
                rate_hits += 1
                if rate_hits > MAX_RATE_RETRIES:
                    self.blocked_domains.add(domain)
                    raise BlockedError(
                        f"HTTP 429 from {domain} after {MAX_RATE_RETRIES} cooldowns -> stopping domain"
                    )
                wait = RATE_COOLDOWN_BASE * 2 ** (rate_hits - 1)
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.strip().isdigit():
                    wait = min(float(retry_after), RATE_COOLDOWN_MAX)
                log.warning(
                    "HTTP 429 from %s -> cooldown %.0fs (%d/%d)",
                    domain, wait, rate_hits, MAX_RATE_RETRIES,
                )
                time.sleep(wait)
                continue

            if resp.status_code in BLOCKING_STATUS:
                # temporary anti-bot wall: cool down (honour Retry-After if given)
                block_hits += 1
                if block_hits > MAX_BLOCK_RETRIES:
                    self.blocked_domains.add(domain)
                    raise BlockedError(
                        f"HTTP {resp.status_code} from {domain} after {MAX_BLOCK_RETRIES} cooldowns -> stopping domain"
                    )
                wait = min(BLOCK_COOLDOWN_BASE * 2 ** (block_hits - 1), BLOCK_COOLDOWN_MAX)
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.strip().isdigit():
                    wait = min(float(retry_after), BLOCK_COOLDOWN_MAX)
                log.warning(
                    "HTTP %d from %s -> cooldown %.0fs (%d/%d)",
                    resp.status_code, domain, wait, block_hits, MAX_BLOCK_RETRIES,
                )
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                raise FetchError(f"HTTP 404 {url}")
            if resp.status_code >= 500:
                attempt += 1
                if attempt >= MAX_RETRIES:
                    raise FetchError(f"giving up on {url}: HTTP {resp.status_code}")
                log.warning("attempt %d/%d server error %s", attempt, MAX_RETRIES, url)
                time.sleep(BACKOFF_BASE**attempt)
                continue
            if resp.status_code >= 400:
                raise FetchError(f"HTTP {resp.status_code} {url}")

            ctype = resp.headers.get("Content-Type", "")
            if ctype and "html" not in ctype and "xml" not in ctype:
                raise FetchError(f"unsupported content-type {ctype!r} for {url}")
            if "charset" not in ctype.lower():
                # no declared charset -> RFC 2616 default (latin-1) mangles UTF-8
                resp.encoding = "utf-8"
            return FetchResult(url=url, final_url=str(resp.url), status=resp.status_code, html=resp.text)
