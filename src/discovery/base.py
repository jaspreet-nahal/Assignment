"""
Base discovery classes and utilities for influencer discovery.
Provides rate limiting, retry logic, and common scraping infrastructure.
"""

import asyncio
import random
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

from src.core.config import get_settings
from src.core.models import InfluencerBase, Platform, Niche, DiscoveryResult


logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Token bucket rate limiter for API requests."""
    requests_per_minute: int
    _tokens: float = field(init=False)
    _last_update: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.requests_per_minute)
        self._last_update = time.monotonic()

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens, waiting if necessary."""
        async with self._lock:
            while self._tokens < tokens:
                now = time.monotonic()
                elapsed = now - self._last_update
                self._tokens = min(
                    self.requests_per_minute,
                    self._tokens + elapsed * (self.requests_per_minute / 60.0)
                )
                self._last_update = now

                if self._tokens < tokens:
                    wait_time = (tokens - self._tokens) * (60.0 / self.requests_per_minute)
                    await asyncio.sleep(wait_time)

            self._tokens -= tokens


class DiscoveryBase(ABC):
    """Abstract base class for platform-specific discovery."""

    def __init__(
        self,
        platform: Platform,
        rate_limit: Optional[int] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.platform = platform
        self.timeout = timeout
        self.max_retries = max_retries

        if rate_limit is None:
            rate_limit = get_settings().discovery.rate_limits.get(platform.value, 30)

        self.rate_limiter = RateLimiter(rate_limit)

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers=self._get_default_headers(),
            follow_redirects=True,
        )

        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
        ]

    def _get_default_headers(self) -> Dict[str, str]:
        """Get default HTTP headers."""
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }

    def _get_random_headers(self) -> Dict[str, str]:
        """Get headers with rotated user agent."""
        headers = self._get_default_headers()
        headers["User-Agent"] = random.choice(self.user_agents)
        return headers

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def _fetch(self, url: str, **kwargs) -> httpx.Response:
        """Fetch URL with rate limiting and retry logic."""
        await self.rate_limiter.acquire()

        headers = kwargs.pop("headers", {})
        merged_headers = {**self._get_random_headers(), **headers}

        response = await self.client.get(url, headers=merged_headers, **kwargs)
        response.raise_for_status()
        return response

    async def _fetch_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """Fetch and parse JSON response."""
        response = await self._fetch(url, **kwargs)
        return response.json()

    async def _fetch_html(self, url: str, **kwargs) -> BeautifulSoup:
        """Fetch and parse HTML response."""
        response = await self._fetch(url, **kwargs)
        return BeautifulSoup(response.text, "lxml")

    @abstractmethod
    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover influencers by hashtag."""
        pass

    @abstractmethod
    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover influencers by search query."""
        pass

    @abstractmethod
    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get detailed profile information for a username."""
        pass

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class MockDiscoveryBase(DiscoveryBase):
    """Mock discovery for testing without API access."""

    def __init__(self, platform: Platform, **kwargs):
        super().__init__(platform, **kwargs)
        self.mock_data = self._generate_mock_data()

    def _generate_mock_data(self) -> List[Dict[str, Any]]:
        """Generate mock influencer data for testing."""
        niches = ["fitness", "fintech", "beauty", "fashion", "crypto", "parenting", "gaming", "lifestyle", "technology"]
        mock_influencers = []

        for i in range(200):
            niche = random.choice(niches)
            follower_count = random.randint(5000, 100000)

            mock_influencers.append({
                "username": f"{niche}_creator_{i}",
                "display_name": f"{niche.title()} Creator {i}",
                "bio": f"Professional {niche} content creator | {random.randint(10, 100)}k followers | DM for collabs",
                "follower_count": follower_count,
                "following_count": random.randint(100, 5000),
                "post_count": random.randint(50, 500),
                "verified": random.random() < 0.1,
                "profile_image_url": f"https://example.com/avatar_{i}.jpg",
                "external_url": f"https://linktr.ee/{niche}_creator_{i}" if random.random() < 0.7 else None,
            })

        return mock_influencers

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Return mock influencers for hashtag."""
        await asyncio.sleep(0.1)

        filtered = self.mock_data
        if niche:
            filtered = [inf for inf in filtered if niche.value in inf["bio"].lower()]

        results = []
        for inf_data in filtered[:limit]:
            results.append(InfluencerBase(
                username=inf_data["username"],
                platform=self.platform,
                profile_url=f"https://{self.platform.value}.com/{inf_data['username']}",
                display_name=inf_data["display_name"],
                bio=inf_data["bio"],
                follower_count=inf_data["follower_count"],
                following_count=inf_data["following_count"],
                post_count=inf_data["post_count"],
                verified=inf_data["verified"],
                profile_image_url=inf_data["profile_image_url"],
                external_url=inf_data["external_url"],
                discovery_method=f"hashtag:{hashtag}",
                raw_data={"hashtag": hashtag, "mock": True},
            ))

        return results

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Return mock influencers for search query."""
        await asyncio.sleep(0.1)

        filtered = self.mock_data
        if niche:
            filtered = [inf for inf in filtered if niche.value in inf["bio"].lower()]

        results = []
        for inf_data in filtered[:limit]:
            results.append(InfluencerBase(
                username=inf_data["username"],
                platform=self.platform,
                profile_url=f"https://{self.platform.value}.com/{inf_data['username']}",
                display_name=inf_data["display_name"],
                bio=inf_data["bio"],
                follower_count=inf_data["follower_count"],
                following_count=inf_data["following_count"],
                post_count=inf_data["post_count"],
                verified=inf_data["verified"],
                profile_image_url=inf_data["profile_image_url"],
                external_url=inf_data["external_url"],
                discovery_method=f"search:{query}",
                raw_data={"query": query, "mock": True},
            ))

        return results

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get mock profile details."""
        await asyncio.sleep(0.05)

        for inf_data in self.mock_data:
            if inf_data["username"] == username:
                return InfluencerBase(
                    username=inf_data["username"],
                    platform=self.platform,
                    profile_url=f"https://{self.platform.value}.com/{inf_data['username']}",
                    display_name=inf_data["display_name"],
                    bio=inf_data["bio"],
                    follower_count=inf_data["follower_count"],
                    following_count=inf_data["following_count"],
                    post_count=inf_data["post_count"],
                    verified=inf_data["verified"],
                    profile_image_url=inf_data["profile_image_url"],
                    external_url=inf_data["external_url"],
                    discovery_method="profile_lookup",
                    raw_data={"mock": True},
                )
        return None


def extract_email(text: str) -> List[str]:
    """Extract email addresses from text."""
    import re
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.findall(email_pattern, text)


def extract_phone(text: str) -> List[str]:
    """Extract phone numbers from text."""
    import re
    phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    return re.findall(phone_pattern, text)


def parse_count(text: str) -> Optional[int]:
    """Parse follower count from text (e.g., '1.5M', '500K', '10,000')."""
    if not text:
        return None

    text = text.strip().upper().replace(",", "").replace(" ", "")

    multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}

    for suffix, multiplier in multipliers.items():
        if text.endswith(suffix):
            try:
                return int(float(text[:-1]) * multiplier)
            except ValueError:
                return None

    try:
        return int(text)
    except ValueError:
        return None


def clean_username(username: str) -> str:
    """Clean and normalize username."""
    return username.strip().lstrip("@").lower()


def is_valid_profile_url(url: str, platform: Platform) -> bool:
    """Validate if URL is a valid profile URL for platform."""
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False

        platform_domains = {
            Platform.INSTAGRAM: ["instagram.com"],
            Platform.YOUTUBE: ["youtube.com", "youtu.be"],
            Platform.TIKTOK: ["tiktok.com"],
            Platform.TWITTER: ["twitter.com", "x.com"],
            Platform.LINKEDIN: ["linkedin.com"],
        }

        return any(domain in parsed.netloc for domain in platform_domains.get(platform, []))
    except Exception:
        return False


def calculate_engagement_rate(
    avg_likes: float,
    avg_comments: float,
    avg_shares: float,
    follower_count: int,
) -> float:
    """Calculate engagement rate as decimal."""
    if follower_count == 0:
        return 0.0
    return (avg_likes + avg_comments + avg_shares) / follower_count


class DiscoveryManager:
    """Manages multiple discovery sources and coordinates concurrent discovery."""

    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.sources: Dict[Platform, DiscoveryBase] = {}
        self._semaphore: Optional[asyncio.Semaphore] = None

    def register_source(self, source: DiscoveryBase) -> None:
        """Register a discovery source."""
        self.sources[source.platform] = source

    def get_source(self, platform: Platform) -> Optional[DiscoveryBase]:
        """Get discovery source for platform."""
        return self.sources.get(platform)

    async def discover_all(
        self,
        niches: List[Niche],
        platforms: List[Platform],
        target_per_niche: int = 50,
        hashtags: Optional[Dict[Niche, List[str]]] = None,
    ) -> DiscoveryResult:
        """Run discovery across all registered sources."""
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

        all_influencers: List[InfluencerBase] = []
        errors: List[str] = []
        rate_limited = False

        tasks = []
        for platform in platforms:
            source = self.get_source(platform)
            if not source:
                errors.append(f"No source registered for platform: {platform.value}")
                continue

            for niche in niches:
                niche_hashtags = hashtags.get(niche, []) if hashtags else [niche.value]

                for hashtag in niche_hashtags:
                    task = self._discover_with_semaphore(
                        source, hashtag, target_per_niche // max(len(niche_hashtags), 1), niche
                    )
                    tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                errors.append(str(result))
                if "rate limit" in str(result).lower() or "429" in str(result):
                    rate_limited = True
            elif isinstance(result, list):
                all_influencers.extend(result)

        seen: Set[tuple] = set()
        unique_influencers = []
        for inf in all_influencers:
            key = (inf.username.lower(), inf.platform)
            if key not in seen:
                seen.add(key)
                unique_influencers.append(inf)

        return DiscoveryResult(
            niche=niches[0] if len(niches) == 1 else Niche.LIFESTYLE,
            platform=platforms[0] if len(platforms) == 1 else Platform.INSTAGRAM,
            influencers_found=len(unique_influencers),
            influencers=unique_influencers[:target_per_niche * len(niches)],
            errors=errors,
            rate_limited=rate_limited,
        )

    async def _discover_with_semaphore(
        self,
        source: DiscoveryBase,
        hashtag: str,
        limit: int,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Discover with semaphore for concurrency control."""
        async with self._semaphore:
            try:
                return await source.discover_by_hashtag(hashtag, limit, niche)
            except Exception as e:
                logger.error(f"Discovery failed for {source.platform.value} #{hashtag}: {e}")
                raise

    async def close_all(self) -> None:
        """Close all registered sources."""
        for source in self.sources.values():
            await source.close()