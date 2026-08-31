"""
TikTok influencer discovery using public pages and scraping.
Note: TikTok has strict anti-bot measures. This uses public hashtag pages.
For production, consider TikTok API or specialized scraping services.
"""

import asyncio
import json
import logging
import re
from typing import List, Optional, Dict, Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from src.core.config import get_settings
from src.core.models import InfluencerBase, Platform, Niche
from src.discovery.base import DiscoveryBase, MockDiscoveryBase

logger = logging.getLogger(__name__)


class TikTokDiscovery(DiscoveryBase):
    """TikTok influencer discovery via public hashtag pages."""

    def __init__(self, use_mock: bool = False, **kwargs):
        if use_mock:
            self._mock = MockDiscoveryBase(Platform.TIKTOK, **kwargs)
        else:
            self._mock = None
        super().__init__(Platform.TIKTOK, **kwargs)

        self.base_url = "https://www.tiktok.com"
        self.hashtag_url = f"{self.base_url}/tag/{{hashtag}}"
        self.search_url = f"{self.base_url}/search/{{query}}"
        self.user_url = f"{self.base_url}/@{{username}}"

        self.client.headers.update({
            "Referer": "https://www.tiktok.com/",
            "Origin": "https://www.tiktok.com",
        })

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,) -> List[InfluencerBase]:
        """Discover creators from a hashtag page."""
        if self._mock:
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

        hashtag = hashtag.lstrip("#")
        url = self.hashtag_url.format(hashtag=quote(hashtag))

        try:
            soup = await self._fetch_html(url)
            return await self._parse_hashtag_page(soup, hashtag, limit, niche)
        except Exception as e:
            logger.error(f"Failed to discover TikTok hashtag #{hashtag}: {e}")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.TIKTOK)
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover creators via TikTok search."""
        if self._mock:
            return await self._mock.discover_by_search(query, limit, niche)

        try:
            url = self.search_url.format(query=quote(query))
            params = {"t": "user"}  # Search for users
            soup = await self._fetch_html(url, params=params)
            return await self._parse_search_page(soup, query, limit, niche)
        except Exception as e:
            logger.error(f"Failed TikTok search for '{query}': {e}")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.TIKTOK)
            return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get detailed profile information."""
        if self._mock:
            return await self._mock.get_profile_details(username)

        username = username.lstrip("@")
        url = self.user_url.format(username=quote(username))

        try:
            soup = await self._fetch_html(url)
            return await self._parse_profile_page(soup, username)
        except Exception as e:
            logger.error(f"Failed to get TikTok profile @{username}: {e}")
            return None

    async def _parse_hashtag_page(
        self,
        soup: BeautifulSoup,
        hashtag: str,
        limit: int,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Parse hashtag page for creator profiles."""
        influencers = []

        script_tags = soup.find_all("script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
        if not script_tags:
            script_tags = soup.find_all("script", text=re.compile(r"__INITIAL_STATE__"))

        for script_tag in script_tags:
            try:
                if script_tag.get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__":
                    data = json.loads(script_tag.string)
                else:
                    match = re.search(r"__INITIAL_STATE__\s*=\s*({.+?});", script_tag.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                    else:
                        continue

                hashtag_data = self._extract_hashtag_data(data)
                if not hashtag_data:
                    continue

                users_seen = set()
                for item in hashtag_data.get("itemList", [])[:limit * 2]:
                    author = item.get("author", {})
                    unique_id = author.get("uniqueId")
                    if not unique_id or unique_id in users_seen:
                        continue
                    users_seen.add(unique_id)

                    stats = author.get("stats", {})
                    follower_count = stats.get("followerCount", 0)

                    if niche and not self._matches_niche_author(author, niche):
                        continue

                    if 5000 <= follower_count <= 100000:
                        influencers.append(InfluencerBase(
                            username=unique_id,
                            platform=Platform.TIKTOK,
                            profile_url=f"{self.base_url}/@{unique_id}",
                            display_name=author.get("nickname"),
                            bio=author.get("signature"),
                            follower_count=follower_count,
                            following_count=stats.get("followingCount"),
                            post_count=stats.get("videoCount"),
                            verified=author.get("verified", False),
                            profile_image_url=author.get("avatarLarger") or author.get("avatarMedium"),
                            external_url=author.get("link"),
                            discovery_method=f"hashtag:{hashtag}",
                            raw_data={
                                "hashtag": hashtag,
                                "is_private": author.get("privateAccount", False),
                                "region": author.get("region"),
                                "sec_uid": author.get("secUid"),
                            }
                        ))

                    if len(influencers) >= limit:
                        break

                if influencers:
                    break

            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                logger.warning(f"Failed to parse TikTok hashtag data: {e}")

        return influencers

    async def _parse_search_page(
        self,
        soup: BeautifulSoup,
        query: str,
        limit: int,
        niche: Optional[Niche],) -> List[InfluencerBase]:
        """Parse search results page."""
        influencers = []

        script_tags = soup.find_all("script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
        if not script_tags:
            script_tags = soup.find_all("script", text=re.compile(r"__INITIAL_STATE__"))

        for script_tag in script_tags:
            try:
                if script_tag.get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__":
                    data = json.loads(script_tag.string)
                else:
                    match = re.search(r"__INITIAL_STATE__\s*=\s*({.+?});", script_tag.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                    else:
                        continue

                user_list = self._extract_search_users(data)
                if not user_list:
                    continue

                for user in user_list[:limit]:
                    unique_id = user.get("uniqueId")
                    if not unique_id:
                        continue

                    stats = user.get("stats", {})
                    follower_count = stats.get("followerCount", 0)

                    if niche and not self._matches_niche_author(user, niche):
                        continue

                    if 5000 <= follower_count <= 100000:
                        influencers.append(InfluencerBase(
                            username=unique_id,
                            platform=Platform.TIKTOK,
                            profile_url=f"{self.base_url}/@{unique_id}",
                            display_name=user.get("nickname"),
                            bio=user.get("signature"),
                            follower_count=follower_count,
                            following_count=stats.get("followingCount"),
                            post_count=stats.get("videoCount"),
                            verified=user.get("verified", False),
                            profile_image_url=user.get("avatarLarger") or user.get("avatarMedium"),
                            external_url=user.get("link"),
                            discovery_method=f"search:{query}",
                            raw_data={
                                "query": query,
                                "is_private": user.get("privateAccount", False),
                                "region": user.get("region"),
                                "sec_uid": user.get("secUid"),
                            }
                        ))

                if influencers:
                    break

            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                logger.warning(f"Failed to parse TikTok search data: {e}")

        return influencers

    async def _parse_profile_page(
        self,
        soup: BeautifulSoup,
        username: str,
    ) -> Optional[InfluencerBase]:
        """Parse individual profile page."""
        meta_data = {}
        for meta in soup.find_all("meta"):
            prop = meta.get("property") or meta.get("name")
            content = meta.get("content")
            if prop and content:
                meta_data[prop] = content

        script_tags = soup.find_all("script", {"id": "__UNIVERSAL_DATA_FOR_REHYDRATION__"})
        if not script_tags:
            script_tags = soup.find_all("script", text=re.compile(r"__INITIAL_STATE__"))

        for script_tag in script_tags:
            try:
                if script_tag.get("id") == "__UNIVERSAL_DATA_FOR_REHYDRATION__":
                    data = json.loads(script_tag.string)
                else:
                    match = re.search(r"__INITIAL_STATE__\s*=\s*({.+?});", script_tag.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                    else:
                        continue

                user_data = self._extract_user_from_page(data)
                if user_data:
                    return self._build_influencer_from_user(user_data, username)

            except (json.JSONDecodeError, KeyError, AttributeError):
                continue

        desc = meta_data.get("og:description", "") or meta_data.get("description", "")
        follower_count = self._parse_meta_count(desc)

        if follower_count and 5000 <= follower_count <= 100000:
            return InfluencerBase(
                username=username,
                platform=Platform.TIKTOK,
                profile_url=f"{self.base_url}/@{username}",
                display_name=meta_data.get("og:title", "").replace(f" (@{username})", ""),
                bio=meta_data.get("description"),
                follower_count=follower_count,
                discovery_method="profile_lookup",
                raw_data={"meta_data": meta_data},
            )

        return None

    def _extract_hashtag_data(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract hashtag data from various possible locations."""
        paths = [
            ["__DEFAULT_SCOPE__", "webapp.video-detail", "itemInfo", "itemStruct", "challenges"],
            ["__DEFAULT_SCOPE__", "webapp.hashtag", "challengeInfo", "challenge"],
            ["__DEFAULT_SCOPE__", "webapp.hashtag", "itemList"],
            ["__DEFAULT_SCOPE__", "webapp.search", "userList"],
        ]

        for path in paths:
            current = data
            for key in path:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    current = None
                    break
            if current:
                return current if isinstance(current, dict) else {"itemList": current}

        return None

    def _extract_search_users(self, data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Extract user list from search results."""
        paths = [
            ["__DEFAULT_SCOPE__", "webapp.search", "userList"],
            ["__DEFAULT_SCOPE__", "webapp.user-list", "userList"],
        ]

        for path in paths:
            current = data
            for key in path:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    current = None
                    break
            if current and isinstance(current, list):
                return current

        return None

    def _extract_user_from_page(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract user data from profile page."""
        paths = [
            ["__DEFAULT_SCOPE__", "webapp.user-detail", "userInfo", "user"],
            ["__DEFAULT_SCOPE__", "webapp.profile", "userInfo", "user"],
        ]

        for path in paths:
            current = data
            for key in path:
                if isinstance(current, dict):
                    current = current.get(key)
                else:
                    current = None
                    break
            if current:
                return current

        return None

    def _build_influencer_from_user(self, user: Dict[str, Any], username: str) -> InfluencerBase:
        """Build InfluencerBase from TikTok user object."""
        stats = user.get("stats", {})

        return InfluencerBase(
            username=username,
            platform=Platform.TIKTOK,
            profile_url=f"{self.base_url}/@{username}",
            display_name=user.get("nickname"),
            bio=user.get("signature"),
            follower_count=stats.get("followerCount", 0),
            following_count=stats.get("followingCount"),
            post_count=stats.get("videoCount"),
            verified=user.get("verified", False),
            profile_image_url=user.get("avatarLarger") or user.get("avatarMedium"),
            external_url=user.get("link"),
            discovery_method="profile_lookup",
            raw_data={
                "sec_uid": user.get("secUid"),
                "is_private": user.get("privateAccount", False),
                "region": user.get("region"),
                "create_time": user.get("createTime"),
                "unique_id": user.get("uniqueId"),
            }
        )

    def _matches_niche_author(self, author: Dict[str, Any], niche: Niche) -> bool:
        """Check if author profile matches niche."""
        text_parts = [
            author.get("nickname", ""),
            author.get("signature", ""),
        ]
        text = " ".join(text_parts).lower()

        niche_terms = {
            Niche.FITNESS: ["fitness", "workout", "gym", "training", "health", "fit"],
            Niche.FINTECH: ["finance", "investing", "money", "crypto", "trading", "wealth"],
            Niche.BEAUTY: ["beauty", "makeup", "skincare", "cosmetics", "grwm"],
            Niche.FASHION: ["fashion", "style", "outfit", "haul", "ootd"],
            Niche.CRYPTO: ["crypto", "bitcoin", "ethereum", "defi", "nft", "web3"],
            Niche.PARENTING: ["mom", "dad", "parenting", "baby", "kids", "family"],
            Niche.GAMING: ["gaming", "gamer", "gameplay", "streamer", "esports"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "routine", "productivity", "travel"],
            Niche.TECHNOLOGY: ["tech", "coding", "programming", "developer", "ai", "software"],
        }

        terms = niche_terms.get(niche, [niche.value])
        return any(term in text for term in terms)

    def _parse_meta_count(self, description: str) -> Optional[int]:
        """Parse follower count from meta description."""
        
        patterns = [
            r"([\d,.]+[KMB]?)\s*followers?",
            r"([\d,.]+[KMB]?)\s*Following",
        ]
        for pattern in patterns:
            match = re.search(pattern, description, re.IGNORECASE)
            if match:
                return self._parse_count(match.group(1))
        return None

    def _parse_count(self, text: str) -> Optional[int]:
        """Parse count string (e.g., '50K', '1.5M')."""
        text = text.strip().upper().replace(",", "")
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

    async def close(self) -> None:
        """Close the HTTP client."""
        await super().close()
        if self._mock:
            await self._mock.close()


class TikTokAPIDiscovery(DiscoveryBase):
    """
    TikTok API discovery (requires TikTok for Developers approval).
    Placeholder for official API integration.
    """

    def __init__(self, access_token: str, **kwargs):
        super().__init__(Platform.TIKTOK, **kwargs)
        self.access_token = access_token
        self.api_base = "https://open.tiktokapis.com/v2"

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        logger.warning("TikTok API hashtag search requires approved developer account")
        return []

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        logger.warning("TikTok API user search requires approved developer account")
        return []

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        logger.warning("TikTok API profile lookup requires approved developer account")
        return None