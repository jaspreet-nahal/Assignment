"""
Public influencer directory scrapers.
Scrapes platforms like Collabstr, Aspire, Grin, and creator newsletters.
"""

import asyncio
import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from src.core.config import get_settings
from src.core.models import InfluencerBase, Platform, Niche
from src.discovery.base import DiscoveryBase, MockDiscoveryBase

logger = logging.getLogger(__name__)


class CollabstrDiscovery(DiscoveryBase):
    """Collabstr public influencer marketplace discovery."""

    def __init__(self, use_mock: bool = False, **kwargs):
        if use_mock:
            self._mock = MockDiscoveryBase(Platform.INSTAGRAM, **kwargs)
        else:
            self._mock = None
        super().__init__(Platform.INSTAGRAM, **kwargs)  # Platform doesn't matter for directories

        self.base_url = "https://collabstr.com"
        self.search_url = f"{self.base_url}/search"

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover influencers by category/keyword on Collabstr."""
        if self._mock:
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

        try:
            # Collabstr uses category-based browsing
            category = self._map_niche_to_category(niche or Niche.LIFESTYLE)
            url = f"{self.base_url}/category/{category}"

            soup = await self._fetch_html(url)
            return await self._parse_collabstr_page(soup, hashtag, limit, niche)
        except Exception as e:
            logger.error(f"Failed Collabstr discovery for {hashtag}: {e}")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.INSTAGRAM)
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Search Collabstr for influencers."""
        if self._mock:
            return await self._mock.discover_by_search(query, limit, niche)

        try:
            params = {
                "q": query,
                "platform": "instagram",  # Default
            }
            soup = await self._fetch_html(self.search_url, params=params)
            return await self._parse_collabstr_page(soup, query, limit, niche)
        except Exception as e:
            logger.error(f"Failed Collabstr search for '{query}': {e}")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.INSTAGRAM)
            return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get influencer details from Collabstr profile."""
        if self._mock:
            return await self._mock.get_profile_details(username)

        try:
            url = f"{self.base_url}/creator/{username.lstrip('@')}"
            soup = await self._fetch_html(url)
            return await self._parse_collabstr_profile(soup, username)
        except Exception as e:
            logger.error(f"Failed to get Collabstr profile {username}: {e}")
            return None

    def _map_niche_to_category(self, niche: Niche) -> str:
        """Map internal niche to Collabstr category."""
        mapping = {
            Niche.FITNESS: "fitness",
            Niche.FINTECH: "finance",
            Niche.BEAUTY: "beauty",
            Niche.FASHION: "fashion",
            Niche.CRYPTO: "crypto",
            Niche.PARENTING: "family",
            Niche.GAMING: "gaming",
            Niche.LIFESTYLE: "lifestyle",
            Niche.TECHNOLOGY: "tech",
        }
        return mapping.get(niche, "lifestyle")

    async def _parse_collabstr_page(
        self,
        soup: BeautifulSoup,
        query: str,
        limit: int,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Parse Collabstr listing page."""
        influencers = []

        # Collabstr uses cards for each creator
        cards = soup.find_all("div", class_=re.compile(r"creator-card|CreatorCard"))

        for card in cards[:limit]:
            try:
                # Extract username
                username_elem = card.find("a", class_=re.compile(r"username|handle"))
                if not username_elem:
                    username_elem = card.find("span", class_=re.compile(r"username|handle"))

                username = username_elem.get_text(strip=True).lstrip("@") if username_elem else None
                if not username:
                    continue

                # Extract follower count
                followers_elem = card.find(text=re.compile(r"follower", re.I))
                if followers_elem:
                    follower_text = followers_elem.find_parent().get_text(strip=True) if followers_elem.find_parent() else ""
                    follower_count = self._parse_count(follower_text)
                else:
                    follower_count = 0

                # Extract platform
                platform_elem = card.find("img", alt=re.compile(r"instagram|youtube|tiktok", re.I))
                platform = Platform.INSTAGRAM
                if platform_elem:
                    alt = platform_elem.get("alt", "").lower()
                    if "youtube" in alt:
                        platform = Platform.YOUTUBE
                    elif "tiktok" in alt:
                        platform = Platform.TIKTOK

                # Extract display name
                name_elem = card.find("h3") or card.find("h4") or card.find(class_=re.compile(r"name"))
                display_name = name_elem.get_text(strip=True) if name_elem else username

                # Extract bio
                bio_elem = card.find(class_=re.compile(r"bio|description"))
                bio = bio_elem.get_text(strip=True) if bio_elem else ""

                if 5000 <= follower_count <= 100000:
                    influencers.append(InfluencerBase(
                        username=username,
                        platform=platform,
                        profile_url=f"{self.base_url}/creator/{username}",
                        display_name=display_name,
                        bio=bio,
                        follower_count=follower_count,
                        discovery_method=f"collabstr:{query}",
                        raw_data={"source": "collabstr", "category": self._map_niche_to_category(niche or Niche.LIFESTYLE)},
                    ))

            except Exception as e:
                logger.warning(f"Failed to parse Collabstr card: {e}")

        return influencers

    async def _parse_collabstr_profile(
        self,
        soup: BeautifulSoup,
        username: str,
    ) -> Optional[InfluencerBase]:
        """Parse individual Collabstr creator profile."""
        # This would parse the detailed profile page
        # For now, return basic info
        return None

    def _parse_count(self, text: str) -> int:
        """Parse follower count from text."""
        text = text.upper().replace(",", "").replace(" ", "")
        multipliers = {"K": 1000, "M": 1000000}
        for suffix, mult in multipliers.items():
            if suffix in text:
                try:
                    return int(float(text.replace(suffix, "")) * mult)
                except ValueError:
                    pass
        try:
            return int(text)
        except ValueError:
            return 0


class AspireDiscovery(DiscoveryBase):
    """Aspire (formerly AspireIQ) public creator directory."""

    def __init__(self, use_mock: bool = True, **kwargs):
        # Aspire requires login for most content, so default to mock
        self._mock = MockDiscoveryBase(Platform.INSTAGRAM, **kwargs)
        super().__init__(Platform.INSTAGRAM, **kwargs)

        self.base_url = "https://aspire.io"

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        return await self._mock.get_profile_details(username)


class GrinDiscovery(DiscoveryBase):
    """Grin creator marketplace (requires login)."""

    def __init__(self, use_mock: bool = True, **kwargs):
        self._mock = MockDiscoveryBase(Platform.INSTAGRAM, **kwargs)
        super().__init__(Platform.INSTAGRAM, **kwargs)

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        return await self._mock.get_profile_details(username)


class CreatorNewsletterDiscovery(DiscoveryBase):
    """Discover influencers from creator newsletters and spotlight pages."""

    def __init__(self, use_mock: bool = False, **kwargs):
        if use_mock:
            self._mock = MockDiscoveryBase(Platform.INSTAGRAM, **kwargs)
        else:
            self._mock = None
        super().__init__(Platform.INSTAGRAM, **kwargs)

        # Known creator newsletter URLs
        self.newsletter_sources = {
            "creatoreconomy": "https://creatoreconomy.so",
            "thepublishpress": "https://thepublishpress.com",
            "linkinbio": "https://linkinbio.com/blog",
            "later": "https://later.com/blog/creator-spotlight",
            "buffer": "https://buffer.com/resources/creators",
        }

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        if self._mock:
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

        all_influencers = []
        for source_name, base_url in self.newsletter_sources.items():
            try:
                influencers = await self._scrape_newsletter_source(source_name, base_url, hashtag, niche)
                all_influencers.extend(influencers)
                if len(all_influencers) >= limit:
                    break
            except Exception as e:
                logger.warning(f"Failed to scrape {source_name}: {e}")

        return all_influencers[:limit]

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        return await self.discover_by_hashtag(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        if self._mock:
            return await self._mock.get_profile_details(username)
        return None

    async def _scrape_newsletter_source(
        self,
        source_name: str,
        base_url: str,
        keyword: str,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Scrape a single newsletter source for creator spotlights."""
        influencers = []

        try:
            # Try to find creator spotlight articles
            search_urls = [
                f"{base_url}/search?q={quote(keyword)}",
                f"{base_url}/category/creators",
                f"{base_url}/tag/{keyword}",
            ]

            for url in search_urls:
                try:
                    soup = await self._fetch_html(url)
                    page_influencers = await self._parse_newsletter_page(soup, source_name, keyword, niche)
                    influencers.extend(page_influencers)
                    if len(influencers) >= 20:
                        break
                except Exception:
                    continue

        except Exception as e:
            logger.warning(f"Failed to scrape newsletter {source_name}: {e}")

        return influencers

    async def _parse_newsletter_page(
        self,
        soup: BeautifulSoup,
        source: str,
        keyword: str,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Parse newsletter article/page for creator mentions."""
        influencers = []

        # Look for Instagram handles in text
        text = soup.get_text()
        handles = re.findall(r"@([a-zA-Z0-9_.]{2,30})", text)

        # Also look for explicit links
        links = soup.find_all("a", href=re.compile(r"instagram\.com/|tiktok\.com/@|youtube\.com/@|youtube\.com/c/"))
        for link in links:
            href = link.get("href", "")
            match = re.search(r"(?:instagram\.com/|tiktok\.com/@|youtube\.com/@|youtube\.com/c/)([^/?#]+)", href)
            if match:
                handles.append(match.group(1))

        # Deduplicate
        unique_handles = list(set(handles))[:20]

        for handle in unique_handles:
            # Create basic influencer entry
            influencers.append(InfluencerBase(
                username=handle,
                platform=Platform.INSTAGRAM,  # Default
                profile_url=f"https://instagram.com/{handle}",
                display_name=handle,
                bio=f"Featured in {source} newsletter",
                follower_count=0,  # Unknown from newsletter
                discovery_method=f"newsletter:{source}:{keyword}",
                raw_data={"source": source, "keyword": keyword, "verified_from_newsletter": True},
            ))

        return influencers


class DirectoryManager:
    """Manages multiple directory sources."""

    def __init__(self):
        self.sources = {
            "collabstr": CollabstrDiscovery(use_mock=True),  # Default to mock
            "aspire": AspireDiscovery(use_mock=True),
            "grin": GrinDiscovery(use_mock=True),
            "newsletters": CreatorNewsletterDiscovery(use_mock=False),
        }

    def get_source(self, name: str) -> Optional[DiscoveryBase]:
        return self.sources.get(name)

    async def discover_all(
        self,
        niches: List[Niche],
        target_per_niche: int = 20,
    ) -> List[InfluencerBase]:
        """Run discovery across all directory sources."""
        all_influencers = []

        for niche in niches:
            for source_name, source in self.sources.items():
                try:
                    hashtags = get_settings().discovery.niches  # Would need niche keywords
                    niche_keywords = [niche.value]

                    for keyword in niche_keywords:
                        results = await source.discover_by_hashtag(keyword, target_per_niche, niche)
                        all_influencers.extend(results)
                except Exception as e:
                    logger.error(f"Directory {source_name} failed for {niche.value}: {e}")

        # Deduplicate
        seen = set()
        unique = []
        for inf in all_influencers:
            key = (inf.username.lower(), inf.platform)
            if key not in seen:
                seen.add(key)
                unique.append(inf)

        return unique

    async def close_all(self) -> None:
        for source in self.sources.values():
            await source.close()


# Export for easy importing
__all__ = [
    "CollabstrDiscovery",
    "AspireDiscovery",
    "GrinDiscovery",
    "CreatorNewsletterDiscovery",
    "DirectoryManager",
]