import asyncio
import logging
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from src.core.config import get_settings, get_niche_keywords
from src.core.models import InfluencerBase,Platform,Niche,DiscoveryResult
from src.discovery.base import DiscoveryBase, DiscoveryManager as BaseDiscoveryManager
from src.discovery.instagram import InstagramDiscovery
from src.discovery.youtube import YouTubeDiscovery
from src.discovery.tiktok import TikTokDiscovery
from src.discovery.directories import DirectoryManager

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryConfig:
    """Configuration for a discovery run."""
    niches: List[Niche]
    platforms: List[Platform]
    target_count: int = 50
    use_mock: bool = True  
    youtube_api_key: Optional[str] = None
    hashtags: Optional[Dict[Niche, List[str]]] = None


class EnhancedDiscoveryManager:
    """Enhanced discovery manager with all platform sources."""

    def __init__(self, config: Optional[DiscoveryConfig] = None):
        self.config = config or DiscoveryConfig(
            niches=[Niche.LIFESTYLE],
            platforms=[Platform.INSTAGRAM, Platform.YOUTUBE, Platform.TIKTOK],
        )
        self.settings = get_settings()
        self.niche_keywords = get_niche_keywords()

        self.sources: Dict[Platform, DiscoveryBase] = {}
        self.directory_manager = DirectoryManager()

        self.all_influencers: List[InfluencerBase] = []
        self.errors: List[str] = []
        self.rate_limited = False

    def initialize_sources(self) -> None:
        """Initialize all discovery sources based on config."""
        use_mock = self.config.use_mock

        if Platform.INSTAGRAM in self.config.platforms:
            self.sources[Platform.INSTAGRAM] = InstagramDiscovery(
                use_mock=use_mock,
                rate_limit=self.settings.discovery.rate_limits.get("instagram", 30),
                timeout=self.settings.discovery.request_timeout,
            )

        if Platform.YOUTUBE in self.config.platforms:
            self.sources[Platform.YOUTUBE] = YouTubeDiscovery(
                api_key=self.config.youtube_api_key,
                use_mock=use_mock,
                rate_limit=self.settings.discovery.rate_limits.get("youtube", 100),
                timeout=self.settings.discovery.request_timeout,
            )

        if Platform.TIKTOK in self.config.platforms:
            self.sources[Platform.TIKTOK] = TikTokDiscovery(
                use_mock=use_mock,
                rate_limit=self.settings.discovery.rate_limits.get("tiktok", 20),
                timeout=self.settings.discovery.request_timeout,
            )

        logger.info(f"Initialized {len(self.sources)} discovery sources")

    async def discover(self) -> DiscoveryResult:
        """Run discovery across all configured sources."""
        self.initialize_sources()
        self.all_influencers = []
        self.errors = []
        self.rate_limited = False

        start_time = datetime.utcnow()

        hashtags = self.config.hashtags or self._get_default_hashtags()

        tasks = []
        for platform in self.config.platforms:
            source = self.sources.get(platform)
            if not source:
                self.errors.append(f"No source for platform: {platform.value}")
                continue

            for niche in self.config.niches:
                niche_hashtags = hashtags.get(niche, [niche.value])

                for hashtag in niche_hashtags:
                    per_hashtag = max(1, self.config.target_count // (len(self.config.niches) * len(niche_hashtags)))
                    task = self._discover_source(source, platform, niche, hashtag, per_hashtag)
                    tasks.append(task)

        if self.config.platforms:  
            dir_task = self._discover_directories()
            tasks.append(dir_task)

        semaphore = asyncio.Semaphore(self.settings.discovery.max_concurrent)

        async def bounded_task(task):
            async with semaphore:
                return await task

        results = await asyncio.gather(
            *[bounded_task(task) for task in tasks],
            return_exceptions=True
        )

        for result in results:
            if isinstance(result, Exception):
                self.errors.append(str(result))
                if "rate limit" in str(result).lower() or "429" in str(result):
                    self.rate_limited = True
                logger.error(f"Discovery task failed: {result}")
            elif isinstance(result, list):
                self.all_influencers.extend(result)

        seen: Set[tuple] = set()
        unique_influencers = []
        for inf in self.all_influencers:
            key = (inf.username.lower(), inf.platform)
            if key not in seen:
                seen.add(key)
                unique_influencers.append(inf)

        unique_influencers.sort(key=lambda x: x.follower_count, reverse=True)

        final_influencers = unique_influencers[:self.config.target_count]

        duration = (datetime.utcnow() - start_time).total_seconds()

        primary_niche = self.config.niches[0] if self.config.niches else Niche.LIFESTYLE
        primary_platform = self.config.platforms[0] if self.config.platforms else Platform.INSTAGRAM

        return DiscoveryResult(
            niche=primary_niche,
            platform=primary_platform,
            influencers_found=len(final_influencers),
            influencers=final_influencers,
            errors=self.errors,
            rate_limited=self.rate_limited,
        )

    async def _discover_source(
        self,
        source: DiscoveryBase,
        platform: Platform,
        niche: Niche,
        hashtag: str,
        limit: int,) -> List[InfluencerBase]:
        """Discover from a single source with error handling."""
        try:
            logger.info(f"Discovering {platform.value} #{hashtag} (limit: {limit})")
            influencers = await source.discover_by_hashtag(hashtag, limit, niche)

            for inf in influencers:
                inf.raw_data.update({
                    "discovery_niche": niche.value,
                    "discovery_platform": platform.value,
                    "discovery_hashtag": hashtag,
                })

            logger.info(f"Found {len(influencers)} influencers from {platform.value} #{hashtag}")
            return influencers

        except Exception as e:
            logger.error(f"Discovery failed for {platform.value} #{hashtag}: {e}")
            raise

    async def _discover_directories(self) -> List[InfluencerBase]:
        """Discover from directory sources."""
        all_influencers = []

        try:
            dir_influencers = await self.directory_manager.discover_all(
                niches=self.config.niches,
                target_per_niche=max(5, self.config.target_count // 10),  
            )
            all_influencers.extend(dir_influencers)
            logger.info(f"Found {len(dir_influencers)} influencers from directories")
        except Exception as e:
            logger.error(f"Directory discovery failed: {e}")

        return all_influencers

    def _get_default_hashtags(self) -> Dict[Niche, List[str]]:
        """Get default hashtags for each niche from config."""
        hashtags = {}
        for niche in self.config.niches:
            niche_tags = self.niche_keywords.get_hashtags(niche)
            if niche_tags:
                hashtags[niche] = niche_tags[:5]  
            else:
                hashtags[niche] = [niche.value]
        return hashtags

    async def close(self) -> None:
        """Close all sources."""
        for source in self.sources.values():
            await source.close()
        await self.directory_manager.close_all()


async def run_discovery(
    niches: List[Niche],
    platforms: List[Platform],
    target_count: int = 50,
    use_mock: bool = True,
    youtube_api_key: Optional[str] = None,) -> DiscoveryResult:
    """Convenience function to run discovery."""
    config = DiscoveryConfig(
        niches=niches,
        platforms=platforms,
        target_count=target_count,
        use_mock=use_mock,
        youtube_api_key=youtube_api_key,
    )

    manager = EnhancedDiscoveryManager(config)
    try:
        result = await manager.discover()
        return result
    finally:
        await manager.close()


class DiscoveryManager(BaseDiscoveryManager):
    """Extended discovery manager with all sources pre-registered."""

    def __init__(self, max_concurrent: int = 5, use_mock: bool = True):
        super().__init__(max_concurrent)
        self.use_mock = use_mock
        self.settings = get_settings()

        # Register all sources
        self.register_source(InstagramDiscovery(use_mock=use_mock))
        self.register_source(YouTubeDiscovery(use_mock=use_mock))
        self.register_source(TikTokDiscovery(use_mock=use_mock))
