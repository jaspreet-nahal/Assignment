"""
Base enrichment classes and utilities for influencer profile enrichment.
Provides rate limiting, retry logic, and common enrichment infrastructure.
"""

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
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

from src.core.config import get_settings
from src.core.models import (
    InfluencerBase,
    EnrichedProfile,
    ContactInfo,
    ContentAnalysis,
    CrossPlatformPresence,
    EngagementMetrics,
    Platform,
    Niche,
)

logger = logging.getLogger(__name__)


@dataclass
class RateLimiter:
    """Token bucket rate limiter for enrichment requests."""
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


class EnrichmentBase(ABC):
    """Abstract base class for platform-specific enrichment."""

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
            rate_limit = get_settings().discovery.rate_limits.get(platform.value, 10)

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

    async def _fetch_html(self, url: str, **kwargs) -> BeautifulSoup:
        """Fetch and parse HTML response."""
        response = await self._fetch(url, **kwargs)
        return BeautifulSoup(response.text, "lxml")

    async def _fetch_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """Fetch and parse JSON response."""
        response = await self._fetch(url, **kwargs)
        return response.json()

    @abstractmethod
    async def enrich_contact(self, influencer: InfluencerBase) -> ContactInfo:
        """Extract contact information from profile and link-in-bio."""
        pass

    @abstractmethod
    async def enrich_content(self, influencer: InfluencerBase, post_count: int = 10) -> ContentAnalysis:
        """Analyze recent content for topics, quality, brand safety."""
        pass

    @abstractmethod
    async def enrich_cross_platform(self, influencer: InfluencerBase) -> CrossPlatformPresence:
        """Check presence on other platforms."""
        pass

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()



def extract_emails(text: str) -> List[str]:
    """Extract email addresses from text."""
    import re
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    return re.findall(email_pattern, text)


def extract_phone(text: str) -> List[str]:
    """Extract phone numbers from text."""
    import re
    phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    return re.findall(phone_pattern, text)


def is_link_in_bio_platform(url: str) -> Optional[str]:
    """Detect link-in-bio platform from URL."""
    if not url:
        return None

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    platforms = {
        "linktr.ee": "linktree",
        "linktree.com": "linktree",
        "beacons.ai": "beacons",
        "beacons.page": "beacons",
        "campsite.bio": "campsite",
        "campsite.bio": "campsite",
        "linkin.bio": "linkinbio",
        "bio.link": "biolink",
        "kite.link": "kite",
        "tap.bio": "tapbio",
        "milkshake.app": "milkshake",
        "contactin.bio": "contactinbio",
        "shorby.com": "shorby",
        "lnk.bio": "lnkbio",
        "allmylinks.com": "allmylinks",
    }

    for key, platform in platforms.items():
        if key in domain:
            return platform

    return "unknown"


async def resolve_link_in_bio(url: str, client: httpx.AsyncClient) -> Dict[str, Any]:
    """
    Resolve link-in-bio page to extract links, emails, and social profiles.
    Returns dict with emails, social_links, and other extracted data.
    """
    result = {
        "emails": [],
        "social_links": {},
        "links": [],
        "platform": is_link_in_bio_platform(url),
    }

    try:
        response = await client.get(url, timeout=10.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = link.get_text(strip=True)
            result["links"].append({"url": href, "text": text})

            for platform in Platform:
                if platform.value in href.lower():
                    result["social_links"][platform.value] = href

        page_text = soup.get_text()
        result["emails"] = extract_emails(page_text)

        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                import json
                ld_data = json.loads(json_ld.string)
                if isinstance(ld_data, dict):
                    if "email" in ld_data:
                        result["emails"].append(ld_data["email"])
            except:
                pass

    except Exception as e:
        logger.warning(f"Failed to resolve link-in-bio {url}: {e}")

    result["emails"] = list(set(result["emails"]))

    return result


def calculate_content_quality_score(
    posts_analyzed: int,
    avg_engagement_rate: float,
    has_sponsored: bool,
    brand_safe: bool,
    consistent_posting: bool,) -> float:
    """Calculate content quality score (0-1)."""
    score = 0.0

    if avg_engagement_rate > 0.05:
        score += 0.3
    elif avg_engagement_rate > 0.03:
        score += 0.2
    elif avg_engagement_rate > 0.01:
        score += 0.1

    if posts_analyzed >= 10:
        score += 0.2
    elif posts_analyzed >= 5:
        score += 0.15
    elif posts_analyzed >= 3:
        score += 0.1

    if brand_safe:
        score += 0.2

    if consistent_posting:
        score += 0.15

    if has_sponsored:
        score += 0.15

    return min(score, 1.0)


def detect_language(text: str) -> str:
    """Simple language detection (placeholder for production)."""
    # In production, use langdetect or similar
    # For now, assume English
    return "en"


def analyze_sentiment(text: str) -> str:
    """Simple sentiment analysis (placeholder for production)."""
    # In production, use textblob, vader, or transformers
    positive_words = ["love", "amazing", "great", "awesome", "best", "happy", "excited", "beautiful", "perfect", "wonderful"]
    negative_words = ["hate", "terrible", "awful", "bad", "worst", "sad", "angry", "disappointed", "horrible", "poor"]

    text_lower = text.lower()
    pos_count = sum(1 for w in positive_words if w in text_lower)
    neg_count = sum(1 for w in negative_words if w in text_lower)

    if pos_count > neg_count:
        return "positive"
    elif neg_count > pos_count:
        return "negative"
    return "neutral"


__all__ = [
    "RateLimiter",
    "EnrichmentBase",
    "extract_emails",
    "extract_phone",
    "is_link_in_bio_platform",
    "resolve_link_in_bio",
    "calculate_content_quality_score",
    "detect_language",
    "analyze_sentiment",
]