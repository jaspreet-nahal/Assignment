"""
Cross-platform presence analysis for influencer enrichment.
Checks for consistent branding and presence across multiple social platforms.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from src.core.models import InfluencerBase, CrossPlatformPresence, Platform
from src.enrichment.base import EnrichmentBase, is_link_in_bio_platform, resolve_link_in_bio

logger = logging.getLogger(__name__)


class CrossPlatformEnricher(EnrichmentBase):
    """Analyzes cross-platform presence and branding consistency."""

    def __init__(self, platform: Platform = Platform.INSTAGRAM, **kwargs):
        super().__init__(platform, **kwargs)

        self.platform_configs = {
            Platform.INSTAGRAM: {
                "base_url": "https://www.instagram.com/{username}/",
                "check_selectors": ["meta[property='og:title']", "meta[property='og:description']"],
                "follower_pattern": r"([\d,.]+[KMB]?)\s*Followers",
            },
            Platform.YOUTUBE: {
                "base_url": "https://www.youtube.com/@{username}",
                "check_selectors": ["meta[property='og:title']", "ytd-channel-name"],
                "follower_pattern": r"([\d,.]+[KMB]?)\s*subscribers?",
            },
            Platform.TIKTOK: {
                "base_url": "https://www.tiktok.com/@{username}",
                "check_selectors": ["meta[property='og:title']", "meta[property='og:description']"],
                "follower_pattern": r"([\d,.]+[KMB]?)\s*Followers",
            },
            Platform.TWITTER: {
                "base_url": "https://x.com/{username}",
                "check_selectors": ["meta[property='og:title']", "meta[name='description']"],
                "follower_pattern": r"([\d,.]+[KMB]?)\s*Followers",
            },
            Platform.LINKEDIN: {
                "base_url": "https://www.linkedin.com/in/{username}",
                "check_selectors": ["meta[property='og:title']", "meta[property='og:description']"],
                "follower_pattern": r"([\d,.]+[KMB]?)\s*followers?",
            },
        }

    async def enrich_cross_platform(self, influencer: InfluencerBase) -> CrossPlatformPresence:
        """
        Main entry point for cross-platform enrichment.
        Checks for presence on other platforms using username matching and link-in-bio.
        """
        platforms: Dict[Platform, Optional[str]] = {influencer.platform: influencer.username}
        total_followers = influencer.follower_count
        platform_count = 1
        consistent_branding = False

        link_in_bio_platforms = await self._extract_platforms_from_link_in_bio(influencer)
        for platform, username in link_in_bio_platforms.items():
            if platform != influencer.platform and username:
                platforms[platform] = username
                platform_count += 1

        other_platforms = [p for p in Platform if p != influencer.platform and p not in platforms]
        username_variations = self._generate_username_variations(influencer.username)

        for platform in other_platforms:
            found_username = await self._check_username_on_platform(platform, username_variations)
            if found_username:
                platforms[platform] = found_username
                platform_count += 1

        follower_data = await self._fetch_follower_counts(platforms, influencer.username)
        for platform, count in follower_data.items():
            if platform != influencer.platform and count:
                total_followers += count

        consistent_branding = await self._check_branding_consistency(platforms, influencer)

        return CrossPlatformPresence(
            platforms=platforms,
            total_followers=total_followers,
            platform_count=platform_count,
            consistent_branding=consistent_branding,
            checked_at=datetime.utcnow(),
        )

    def _generate_username_variations(self, username: str) -> List[str]:
        """Generate common username variations to check."""
        variations = [username]
        clean = username.lower().replace(".", "").replace("_", "").replace("-", "")

        variations.extend([
            username.replace(".", ""),
            username.replace("_", ""),
            username.replace("-", ""),
            username.replace(".", "_"),
            username.replace(".", "-"),
            username.replace("_", "."),
            username.replace("-", "."),
            clean,
            f"{clean}official",
            f"official{clean}",
            f"the{clean}",
            f"{clean}hq",
        ])

        seen = set()
        unique = []
        for v in variations:
            if v not in seen:
                seen.add(v)
                unique.append(v)

        return unique

    async def _extract_platforms_from_link_in_bio(self, influencer: InfluencerBase) -> Dict[Platform, str]:
        """Extract platform usernames from link-in-bio page."""
        platforms = {}

        if not influencer.external_url:
            return platforms

        try:
            link_data = await resolve_link_in_bio(str(influencer.external_url), self.client)
            social_links = link_data.get("social_links", {})

            for platform_str, url in social_links.items():
                try:
                    platform = Platform(platform_str)
                    username = self._extract_username_from_url(platform, url)
                    if username:
                        platforms[platform] = username
                except ValueError:
                    pass

        except Exception as e:
            logger.warning(f"Failed to extract platforms from link-in-bio: {e}")

        return platforms

    def _extract_username_from_url(self, platform: Platform, url: str) -> Optional[str]:
        """Extract username from platform profile URL."""
        try:
            parsed = urlparse(url)
            path = parsed.path.strip("/")

            if platform == Platform.INSTAGRAM:
                return path.split("/")[0] if path else None
            elif platform == Platform.YOUTUBE:
                if path.startswith("@"):
                    return path[1:]
                elif path.startswith("c/"):
                    return path[2:]
                elif path.startswith("channel/"):
                    return path[8:]  
                return path
            elif platform == Platform.TIKTOK:
                if path.startswith("@"):
                    return path[1:]
                return path
            elif platform == Platform.TWITTER:
                return path
            elif platform == Platform.LINKEDIN:
                if path.startswith("in/"):
                    return path[3:]
                return path

        except Exception:
            pass

        return None

    async def _check_username_on_platform(self, platform: Platform, usernames: List[str]) -> Optional[str]:
        """Check if any username variation exists on platform."""
        config = self.platform_configs.get(platform)
        if not config:
            return None

        base_url = config["base_url"]

        for username in usernames[:5]:  
            url = base_url.format(username=username)
            try:
                response = await self._fetch(url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "lxml")

                    title = soup.find("title")
                    if title and username.lower() in title.get_text().lower():
                        return username

                    og_title = soup.find("meta", property="og:title")
                    if og_title and og_title.get("content") and username.lower() in og_title["content"].lower():
                        return username

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  
            except Exception:
                continue

        return None

    async def _fetch_follower_counts(self, platforms: Dict[Platform, str], primary_username: str) -> Dict[Platform, int]:
        """Fetch follower counts for known platform usernames."""
        follower_counts = {}

        semaphore = asyncio.Semaphore(3)

        async def fetch_one(platform: Platform, username: str):
            async with semaphore:
                config = self.platform_configs.get(platform)
                if not config:
                    return platform, 0

                base_url = config["base_url"]
                pattern = config["follower_pattern"]

                try:
                    url = base_url.format(username=username)
                    response = await self._fetch(url)
                    soup = BeautifulSoup(response.text, "lxml")

                    page_text = soup.get_text()
                    match = re.search(pattern, page_text, re.IGNORECASE)
                    if match:
                        count_str = match.group(1)
                        count = self._parse_count(count_str)
                        return platform, count

                except Exception as e:
                    logger.debug(f"Failed to fetch followers for {platform.value}/{username}: {e}")

                return platform, 0

        tasks = [
            fetch_one(platform, username)
            for platform, username in platforms.items()
            if platform != self.platform
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple):
                platform, count = result
                if count > 0:
                    follower_counts[platform] = count

        return follower_counts

    def _parse_count(self, text: str) -> int:
        """Parse count string (e.g., '10K', '1.5M')."""
        text = text.strip().upper().replace(",", "")
        multipliers = {"K": 1000, "M": 1000000, "B": 1000000000}

        for suffix, multiplier in multipliers.items():
            if text.endswith(suffix):
                try:
                    return int(float(text[:-1]) * multiplier)
                except ValueError:
                    return 0

        try:
            return int(text)
        except ValueError:
            return 0

    async def _check_branding_consistency(
        self,
        platforms: Dict[Platform, str],
        influencer: InfluencerBase,
    ) -> bool:
        """Check if branding is consistent across platforms."""
        if len(platforms) < 2:
            return False

        profile_data = {}

        semaphore = asyncio.Semaphore(3)

        async def fetch_profile(platform: Platform, username: str):
            async with semaphore:
                config = self.platform_configs.get(platform)
                if not config:
                    return platform, {}

                try:
                    url = config["base_url"].format(username=username)
                    response = await self._fetch(url)
                    soup = BeautifulSoup(response.text, "lxml")

                    data = {}
                    og_title = soup.find("meta", property="og:title")
                    if og_title:
                        data["display_name"] = og_title.get("content", "")

                    og_desc = soup.find("meta", property="og:description")
                    if og_desc:
                        data["bio"] = og_desc.get("content", "")

                    og_image = soup.find("meta", property="og:image")
                    if og_image:
                        data["profile_image"] = og_image.get("content", "")

                    return platform, data
                except Exception:
                    return platform, {}

        tasks = [fetch_profile(p, u) for p, u in platforms.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, tuple):
                platform, data = result
                if data:
                    profile_data[platform] = data

        if len(profile_data) < 2:
            return False

        display_names = [d.get("display_name", "").lower() for d in profile_data.values() if d.get("display_name")]
        if display_names:
            common_words = set(display_names[0].split())
            for name in display_names[1:]:
                common_words &= set(name.split())
            if len(common_words) >= 1: 
                return True

        bios = [d.get("bio", "").lower() for d in profile_data.values() if d.get("bio")]
        if bios:
            common_bio_words = set(bios[0].split())
            for bio in bios[1:]:
                common_bio_words &= set(bio.split())
            meaningful = {w for w in common_bio_words if len(w) > 3}
            if len(meaningful) >= 2:
                return True

        images = [d.get("profile_image", "") for d in profile_data.values() if d.get("profile_image")]
        if len(images) >= 2:
            domains = [urlparse(img).netloc for img in images]
            if len(set(domains)) == 1:
                return True

        return False

    async def enrich_contact(self, influencer: InfluencerBase):
        """Not implemented in cross-platform enricher."""
        raise NotImplementedError("Use ContactEnricher for contact extraction")

    async def enrich_content(self, influencer: InfluencerBase, post_count: int = 10):
        """Not implemented in cross-platform enricher."""
        raise NotImplementedError("Use ContentEnricher for content analysis")


__all__ = [
    "CrossPlatformEnricher",
]