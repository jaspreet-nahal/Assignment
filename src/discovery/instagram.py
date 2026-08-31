"""
Instagram influencer discovery using public pages and scraping.
Note: Instagram has strict anti-scraping measures. This uses public hashtag pages
and search results. For production, consider using Instagram Graph API.
"""

import asyncio
import json
import re
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import quote

from bs4 import BeautifulSoup

from src.core.config import get_settings
from src.core.models import InfluencerBase, Platform, Niche
from src.discovery.base import DiscoveryBase, MockDiscoveryBase

logger = logging.getLogger(__name__)


class InstagramDiscovery(DiscoveryBase):
    """Instagram influencer discovery via public hashtag pages."""

    def __init__(self, use_mock: bool = False, **kwargs):
        if use_mock:
            self._mock = MockDiscoveryBase(Platform.INSTAGRAM, **kwargs)
        else:
            self._mock = None
        super().__init__(Platform.INSTAGRAM, **kwargs)

        self.base_url = "https://www.instagram.com"
        self.hashtag_url = f"{self.base_url}/explore/tags/{{hashtag}}/"
        self.search_url = f"{self.base_url}/web/search/topsearch/"

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover influencers from a hashtag page."""
        if self._mock:
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

        hashtag = hashtag.lstrip("#")
        url = self.hashtag_url.format(hashtag=quote(hashtag))

        try:
            soup = await self._fetch_html(url)
            return await self._parse_hashtag_page(soup, hashtag, limit, niche)
        except Exception as e:
            logger.error(f"Failed to discover Instagram hashtag #{hashtag}: {e}")
            logger.warning("Falling back to mock data")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.INSTAGRAM)
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover influencers via Instagram search."""
        if self._mock:
            return await self._mock.discover_by_search(query, limit, niche)

        try:
            params = {
                "context": "blended",
                "query": query,
                "rank_token": self._generate_rank_token(),
                "include_reel": "true",
            }
            response = await self._fetch_json(self.search_url, params=params)
            return await self._parse_search_results(response, query, limit, niche)
        except Exception as e:
            logger.error(f"Failed Instagram search for '{query}': {e}")
            if not self._mock:
                self._mock = MockDiscoveryBase(Platform.INSTAGRAM)
            return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get detailed profile information."""
        if self._mock:
            return await self._mock.get_profile_details(username)

        username = username.lstrip("@")
        url = f"{self.base_url}/{username}/"

        try:
            soup = await self._fetch_html(url)
            return await self._parse_profile_page(soup, username)
        except Exception as e:
            logger.error(f"Failed to get Instagram profile @{username}: {e}")
            return None

    async def _parse_hashtag_page(
        self,
        soup: BeautifulSoup,
        hashtag: str,
        limit: int,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Parse hashtag page for influencer profiles."""
        influencers = []

        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            script_tag = soup.find("script", text=re.compile(r"window\._sharedData"))

        if script_tag:
            try:
                if script_tag.get("id") == "__NEXT_DATA__":
                    data = json.loads(script_tag.string)
                else:
                    match = re.search(r"window\._sharedData\s*=\s*({.+?});", script_tag.string, re.DOTALL)
                    if match:
                        data = json.loads(match.group(1))
                    else:
                        data = {}

                hashtag_data = data.get("entry_data", {}).get("TagPage", [{}])[0]
                if not hashtag_data:
                    hashtag_data = data.get("props", {}).get("pageProps", {})

                sections = hashtag_data.get("graphql", {}).get("hashtag", {})
                if not sections:
                    sections = hashtag_data.get("hashtag", {})

                edges = []
                for key in ["edge_hashtag_to_top_posts", "edge_hashtag_to_media"]:
                    if key in sections:
                        edges.extend(sections[key].get("edges", []))

                for edge in edges[:limit]:
                    node = edge.get("node", {})
                    owner = node.get("owner", {})

                    username = owner.get("username")
                    if not username:
                        continue

                    follower_count = owner.get("edge_followed_by", {}).get("count", 0)

                    if niche and not self._matches_niche(node, niche):
                        continue

                    if 5000 <= follower_count <= 100000:
                        influencers.append(InfluencerBase(
                            username=username,
                            platform=Platform.INSTAGRAM,
                            profile_url=f"{self.base_url}/{username}/",
                            display_name=owner.get("full_name"),
                            bio=owner.get("biography"),
                            follower_count=follower_count,
                            following_count=owner.get("edge_follow", {}).get("count"),
                            post_count=owner.get("edge_owner_to_timeline_media", {}).get("count"),
                            verified=owner.get("is_verified", False),
                            profile_image_url=owner.get("profile_pic_url"),
                            external_url=owner.get("external_url"),
                            discovery_method=f"hashtag:{hashtag}",
                            raw_data={
                                "hashtag": hashtag,
                                "is_private": owner.get("is_private", False),
                                "is_business": owner.get("is_business_account", False),
                            }
                        ))

            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                logger.warning(f"Failed to parse hashtag page data: {e}")

        return influencers

    async def _parse_search_results(
        self,
        response: Dict[str, Any],
        query: str,
        limit: int,
        niche: Optional[Niche],
    ) -> List[InfluencerBase]:
        """Parse search API results."""
        influencers = []

        users = response.get("users", [])
        for user_data in users[:limit]:
            user = user_data.get("user", {})
            username = user.get("username")
            if not username:
                continue

            follower_count = user.get("follower_count", 0)

            if niche and not self._matches_niche_user(user, niche):
                continue

            if 5000 <= follower_count <= 100000:
                influencers.append(InfluencerBase(
                    username=username,
                    platform=Platform.INSTAGRAM,
                    profile_url=f"{self.base_url}/{username}/",
                    display_name=user.get("full_name"),
                    bio=user.get("biography"),
                    follower_count=follower_count,
                    following_count=user.get("following_count"),
                    post_count=user.get("media_count"),
                    verified=user.get("is_verified", False),
                    profile_image_url=user.get("profile_pic_url"),
                    external_url=user.get("external_url"),
                    discovery_method=f"search:{query}",
                    raw_data={
                        "is_private": user.get("is_private", False),
                        "is_business": user.get("is_business", False),
                        "category": user.get("category"),
                    }
                ))

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

        json_ld = soup.find("script", {"type": "application/ld+json"})
        if json_ld:
            try:
                ld_data = json.loads(json_ld.string)
                if isinstance(ld_data, dict):
                    meta_data.update(ld_data)
            except json.JSONDecodeError:
                pass

        script_tag = soup.find("script", text=re.compile(r"window\._sharedData"))
        if script_tag:
            match = re.search(r"window\._sharedData\s*=\s*({.+?});", script_tag.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    profile_data = data.get("entry_data", {}).get("ProfilePage", [{}])[0]
                    user = profile_data.get("graphql", {}).get("user", {})
                    if user:
                        return self._build_influencer_from_user(user, username)
                except (json.JSONDecodeError, KeyError):
                    pass

        follower_count = self._parse_meta_count(meta_data.get("og:description", ""))

        if follower_count and 5000 <= follower_count <= 100000:
            return InfluencerBase(
                username=username,
                platform=Platform.INSTAGRAM,
                profile_url=f"{self.base_url}/{username}/",
                display_name=meta_data.get("og:title", "").replace(" (@{username})", ""),
                bio=meta_data.get("description"),
                follower_count=follower_count,
                discovery_method="profile_lookup",
                raw_data={"meta_data": meta_data},
            )

        return None

    def _build_influencer_from_user(self, user: Dict[str, Any], username: str) -> InfluencerBase:
        """Build InfluencerBase from Instagram user object."""
        return InfluencerBase(
            username=username,
            platform=Platform.INSTAGRAM,
            profile_url=f"{self.base_url}/{username}/",
            display_name=user.get("full_name"),
            bio=user.get("biography"),
            follower_count=user.get("edge_followed_by", {}).get("count", 0),
            following_count=user.get("edge_follow", {}).get("count"),
            post_count=user.get("edge_owner_to_timeline_media", {}).get("count"),
            verified=user.get("is_verified", False),
            profile_image_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url"),
            external_url=user.get("external_url"),
            discovery_method="profile_lookup",
            raw_data={
                "is_private": user.get("is_private", False),
                "is_business": user.get("is_business_account", False),
                "category": user.get("business_category_name"),
            }
        )

    def _matches_niche(self, post_node: Dict[str, Any], niche: Niche) -> bool:
        """Check if post matches niche via caption/hashtags."""
        niche_keywords = get_settings().discovery.niches
        caption = post_node.get("edge_media_to_caption", {}).get("edges", [])
        caption_text = " ".join([e["node"]["text"] for e in caption if e.get("node")]).lower()

        niche_terms = {
            Niche.FITNESS: ["fitness", "workout", "gym", "training", "health"],
            Niche.FINTECH: ["finance", "investing", "crypto", "bitcoin", "trading"],
            Niche.BEAUTY: ["beauty", "skincare", "makeup", "cosmetics"],
            Niche.FASHION: ["fashion", "style", "outfit", "ootd", "streetwear"],
            Niche.CRYPTO: ["crypto", "bitcoin", "ethereum", "defi", "nft", "web3"],
            Niche.PARENTING: ["parenting", "mom", "dad", "baby", "kids", "family"],
            Niche.GAMING: ["gaming", "gamer", "esports", "twitch", "streamer"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "routine", "productivity", "wellness"],
            Niche.TECHNOLOGY: ["tech", "programming", "coding", "developer", "ai", "software"],
        }

        terms = niche_terms.get(niche, [niche.value])
        return any(term in caption_text for term in terms)

    def _matches_niche_user(self, user: Dict[str, Any], niche: Niche) -> bool:
        """Check if user profile matches niche."""
        bio = (user.get("biography") or "").lower()
        category = (user.get("category") or "").lower()
        full_name = (user.get("full_name") or "").lower()

        niche_terms = {
            Niche.FITNESS: ["fitness", "workout", "gym", "training", "health", "coach", "trainer"],
            Niche.FINTECH: ["finance", "investing", "crypto", "bitcoin", "trading", "wealth"],
            Niche.BEAUTY: ["beauty", "skincare", "makeup", "cosmetics", "mua", "esthetician"],
            Niche.FASHION: ["fashion", "style", "outfit", "ootd", "streetwear", "model", "stylist"],
            Niche.CRYPTO: ["crypto", "bitcoin", "ethereum", "defi", "nft", "web3", "blockchain"],
            Niche.PARENTING: ["mom", "dad", "parenting", "baby", "kids", "family", "motherhood"],
            Niche.GAMING: ["gaming", "gamer", "esports", "twitch", "streamer", "stream"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "routine", "productivity", "wellness", "travel"],
            Niche.TECHNOLOGY: ["tech", "programming", "coding", "developer", "ai", "software", "engineer"],
        }

        terms = niche_terms.get(niche, [niche.value])
        text = f"{bio} {category} {full_name}"
        return any(term in text for term in terms)

    def _parse_meta_count(self, description: str) -> Optional[int]:
        """Parse follower count from meta description."""
        import re
        match = re.search(r"([\d,.]+[KMB]?)\s*Followers", description, re.IGNORECASE)
        if match:
            return self._parse_count(match.group(1))
        return None

    def _parse_count(self, text: str) -> Optional[int]:
        """Parse count string (e.g., '10K', '1.5M')."""
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

    def _generate_rank_token(self) -> str:
        """Generate a random rank token for search."""
        import random
        return str(random.random())[2:]

    async def close(self) -> None:
        """Close the HTTP client."""
        await super().close()
        if self._mock:
            await self._mock.close()


class InstagramAPI高iscovery(DiscoveryBase):
    """
    Instagram Graph API discovery (requires Business/Creator account and app approval).
    This is a placeholder for when official API access is available.
    """

    def __init__(self, access_token: str, **kwargs):
        super().__init__(Platform.INSTAGRAM, **kwargs)
        self.access_token = access_token
        self.api_base = "https://graph.facebook.com/v18.0"

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover via Instagram Graph API hashtag search."""
        logger.warning("Instagram Graph API hashtag search requires approved app")
        return []

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover via Instagram Graph API user search."""
        logger.warning("Instagram Graph API user search requires approved app")
        return []

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get profile via Instagram Graph API."""
        logger.warning("Instagram Graph API profile lookup requires approved app")
        return None