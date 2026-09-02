import asyncio
import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
import httpx
from src.core.config import get_settings
from src.core.models import InfluencerBase, Platform, Niche
from src.discovery.base import DiscoveryBase, MockDiscoveryBase

logger = logging.getLogger(__name__)


class YouTubeDiscovery(DiscoveryBase):
    """YouTube influencer discovery via YouTube Data API v3."""

    def __init__(self, api_key: Optional[str] = None, use_mock: bool = False, **kwargs):
        if use_mock:
            self._mock = MockDiscoveryBase(Platform.YOUTUBE, **kwargs)
        else:
            self._mock = None
        super().__init__(Platform.YOUTUBE, **kwargs)

        self.api_key = api_key or get_settings().youtube_api_key or os.getenv("YOUTUBE_API_KEY")
        self.api_base = "https://www.googleapis.com/youtube/v3"

        if not self.api_key and not use_mock:
            logger.warning("No YouTube API key provided. Set YOUTUBE_API_KEY environment variable.")
            logger.warning("Falling back to mock data for development.")
            self._mock = MockDiscoveryBase(Platform.YOUTUBE, **kwargs)

    async def discover_by_hashtag(
        self,
        hashtag: str,
        limit: int = 50,
        niche: Optional[Niche] = None,) -> List[InfluencerBase]:
        """Discover channels by hashtag/search query."""
        if self._mock:
            return await self._mock.discover_by_hashtag(hashtag, limit, niche)

        if not self.api_key:
            return []

        try:
            search_query = f"#{hashtag.lstrip('#')}"
            return await self._search_channels(search_query, limit, niche)
        except Exception as e:
            logger.error(f"Failed YouTube hashtag search #{hashtag}: {e}")
            return []

    async def discover_by_search(
        self,
        query: str,
        limit: int = 50,
        niche: Optional[Niche] = None,
    ) -> List[InfluencerBase]:
        """Discover channels by search query."""
        if self._mock:
            return await self._mock.discover_by_search(query, limit, niche)

        if not self.api_key:
            return []

        try:
            return await self._search_channels(query, limit, niche)
        except Exception as e:
            logger.error(f"Failed YouTube search for '{query}': {e}")
            return []

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        """Get detailed channel information."""
        if self._mock:
            return await self._mock.get_profile_details(username)

        if not self.api_key:
            return None

        try:
            channel_id = await self._resolve_channel_id(username)
            if channel_id:
                return await self._get_channel_details(channel_id)
            return None
        except Exception as e:
            logger.error(f"Failed to get YouTube channel @{username}: {e}")
            return None

    async def _search_channels(
        self,
        query: str,
        limit: int,
        niche: Optional[Niche],) -> List[InfluencerBase]:
        """Search for channels and get their details."""
        search_params = {
            "part": "snippet",
            "q": query,
            "type": "channel",
            "maxResults": min(limit * 2, 50),
            "order": "relevance",
            "key": self.api_key,
        }

        response = await self._fetch_json(f"{self.api_base}/search", params=search_params)
        items = response.get("items", [])

        channel_ids = [
            item["snippet"]["channelId"]
            for item in items
            if item.get("id", {}).get("kind") == "youtube#channel"
        ]

        if not channel_ids:
            return []

        influencers = []
        for i in range(0, len(channel_ids), 50):
            batch_ids = channel_ids[i:i+50]
            channels = await self._get_channels_batch(batch_ids)

            for channel in channels:
                influencer = self._build_influencer(channel, query)
                if influencer:
                    if niche and not self._matches_niche(influencer, niche):
                        continue
                    if 5000 <= influencer.follower_count <= 100000:
                        influencers.append(influencer)

                    if len(influencers) >= limit:
                        break

            if len(influencers) >= limit:
                break

        return influencers[:limit]

    async def _get_channels_batch(self, channel_ids: List[str]) -> List[Dict[str, Any]]:
        """Get detailed channel info for multiple channels."""
        params = {
            "part": "snippet,statistics,brandingSettings,topicDetails",
            "id": ",".join(channel_ids),
            "key": self.api_key,
        }

        response = await self._fetch_json(f"{self.api_base}/channels", params=params)
        return response.get("items", [])

    async def _get_channel_details(self, channel_id: str) -> Optional[InfluencerBase]:
        """Get detailed info for a single channel."""
        channels = await self._get_channels_batch([channel_id])
        if channels:
            return self._build_influencer(channels[0], "profile_lookup")
        return None

    async def _resolve_channel_id(self, username: str) -> Optional[str]:
        """Resolve username/handle to channel ID."""
        if username.startswith("@"):
            username = username[1:]

        params = {
            "part": "snippet",
            "forHandle": username,
            "key": self.api_key,
        }

        response = await self._fetch_json(f"{self.api_base}/channels", params=params)
        items = response.get("items", [])
        if items:
            return items[0]["id"]

        params = {
            "part": "snippet",
            "forUsername": username,
            "key": self.api_key,
        }

        response = await self._fetch_json(f"{self.api_base}/channels", params=params)
        items = response.get("items", [])
        if items:
            return items[0]["id"]

        params = {
            "part": "snippet",
            "q": username,
            "type": "channel",
            "maxResults": 1,
            "key": self.api_key,
        }

        response = await self._fetch_json(f"{self.api_base}/search", params=params)
        items = response.get("items", [])
        if items:
            return items[0]["snippet"]["channelId"]

        return None

    def _build_influencer(self, channel: Dict[str, Any], discovery_method: str) -> Optional[InfluencerBase]:
        """Build InfluencerBase from YouTube channel data."""
        try:
            snippet = channel.get("snippet", {})
            statistics = channel.get("statistics", {})
            branding = channel.get("brandingSettings", {})

            channel_id = channel["id"]
            subscriber_count = int(statistics.get("subscriberCount", 0))

            if statistics.get("hiddenSubscriberCount", False):
                return None

            return InfluencerBase(
                username=snippet.get("customUrl", "").lstrip("@") or channel_id,
                platform=Platform.YOUTUBE,
                profile_url=f"https://www.youtube.com/channel/{channel_id}",
                display_name=snippet.get("title"),
                bio=snippet.get("description"),
                follower_count=subscriber_count,
                following_count=None,
                post_count=int(statistics.get("videoCount", 0)),
                verified=False,
                profile_image_url=snippet.get("thumbnails", {}).get("high", {}).get("url"),
                external_url=branding.get("channel", {}).get("featuredLinksUrl"),
                discovery_method=discovery_method,
                raw_data={
                    "channel_id": channel_id,
                    "published_at": snippet.get("publishedAt"),
                    "country": snippet.get("country"),
                    "topic_categories": channel.get("topicDetails", {}).get("topicCategories", []),
                    "keywords": branding.get("channel", {}).get("keywords"),
                    "view_count": int(statistics.get("viewCount", 0)),
                }
            )
        except Exception as e:
            logger.error(f"Failed to build influencer from channel data: {e}")
            return None

    def _matches_niche(self, influencer: InfluencerBase, niche: Niche) -> bool:
        """Check if channel matches niche."""
        text_parts = [
            influencer.display_name or "",
            influencer.bio or "",
            " ".join(influencer.raw_data.get("topic_categories", [])),
            influencer.raw_data.get("keywords", ""),
        ]
        text = " ".join(text_parts).lower()

        niche_terms = {
            Niche.FITNESS: ["fitness", "workout", "gym", "training", "health", "exercise", "bodybuilding", "yoga"],
            Niche.FINTECH: ["finance", "investing", "money", "stock", "crypto", "trading", "wealth", "personal finance"],
            Niche.BEAUTY: ["beauty", "makeup", "skincare", "cosmetics", "tutorial", "grwm"],
            Niche.FASHION: ["fashion", "style", "outfit", "haul", "lookbook", "streetwear"],
            Niche.CRYPTO: ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "nft", "web3", "trading"],
            Niche.PARENTING: ["parenting", "mom", "dad", "family", "baby", "kids", "motherhood", "fatherhood"],
            Niche.GAMING: ["gaming", "gameplay", "walkthrough", "lets play", "streamer", "esports"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "daily", "routine", "productivity", "minimalism", "travel"],
            Niche.TECHNOLOGY: ["tech", "programming", "coding", "developer", "software", "ai", "tutorial", "review"],
        }

        terms = niche_terms.get(niche, [niche.value])
        return any(term in text for term in terms)

    async def get_channel_stats(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get recent video statistics for engagement calculation."""
        if not self.api_key:
            return None

        try:
            params = {
                "part": "snippet,statistics",
                "channelId": channel_id,
                "order": "date",
                "maxResults": 10,
                "key": self.api_key,
            }

            response = await self._fetch_json(f"{self.api_base}/search", params=params)
            video_ids = [
                item["id"]["videoId"]
                for item in response.get("items", [])
                if item.get("id", {}).get("kind") == "youtube#video"
            ]

            if not video_ids:
                return None

            params = {
                "part": "statistics",
                "id": ",".join(video_ids),
                "key": self.api_key,
            }

            response = await self._fetch_json(f"{self.api_base}/videos", params=params)
            videos = response.get("items", [])

            if not videos:
                return None

            total_views = sum(int(v["statistics"].get("viewCount", 0)) for v in videos)
            total_likes = sum(int(v["statistics"].get("likeCount", 0)) for v in videos)
            total_comments = sum(int(v["statistics"].get("commentCount", 0)) for v in videos)

            return {
                "videos_analyzed": len(videos),
                "avg_views": total_views / len(videos),
                "avg_likes": total_likes / len(videos),
                "avg_comments": total_comments / len(videos),
                "engagement_rate": (total_likes + total_comments) / total_views if total_views > 0 else 0,
            }
        except Exception as e:
            logger.error(f"Failed to get channel stats for {channel_id}: {e}")
            return None

    async def close(self) -> None:
        """Close the HTTP client."""
        await super().close()
        if self._mock:
            await self._mock.close()


class YouTubeTrendingDiscovery(DiscoveryBase):
    """
    Alternative: Discover from trending/popular videos in niche categories.
    Doesn't require API key but less targeted.
    """

    def __init__(self, **kwargs):
        self._mock = MockDiscoveryBase(Platform.YOUTUBE, **kwargs)
        super().__init__(Platform.YOUTUBE, **kwargs)

    async def discover_by_hashtag(self, hashtag: str, limit: int = 50, niche: Optional[Niche] = None) -> List[InfluencerBase]:
        return await self._mock.discover_by_hashtag(hashtag, limit, niche)

    async def discover_by_search(self, query: str, limit: int = 50, niche: Optional[Niche] = None) -> List[InfluencerBase]:
        return await self._mock.discover_by_search(query, limit, niche)

    async def get_profile_details(self, username: str) -> Optional[InfluencerBase]:
        return await self._mock.get_profile_details(username)
