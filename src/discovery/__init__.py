"""
Discovery module for Micro-Influencer Outreach System.
Provides influencer discovery from multiple platforms and sources.
"""

from src.discovery.base import (
    DiscoveryBase,
    MockDiscoveryBase,
    RateLimiter,
    DiscoveryManager as BaseDiscoveryManager,
    extract_email,
    extract_phone,
    parse_count,
    clean_username,
    is_valid_profile_url,
    calculate_engagement_rate,
)

from src.discovery.instagram import InstagramDiscovery, InstagramAPI高iscovery
from src.discovery.youtube import YouTubeDiscovery, YouTubeTrendingDiscovery
from src.discovery.tiktok import TikTokDiscovery, TikTokAPIDiscovery
from src.discovery.directories import (
    CollabstrDiscovery,
    AspireDiscovery,
    GrinDiscovery,
    CreatorNewsletterDiscovery,
    DirectoryManager,
)
from src.discovery.manager import (
    EnhancedDiscoveryManager,
    DiscoveryConfig,
    run_discovery,
    DiscoveryManager,
)

__all__ = [
    # Base
    "DiscoveryBase",
    "MockDiscoveryBase",
    "RateLimiter",
    "BaseDiscoveryManager",
    "extract_email",
    "extract_phone",
    "parse_count",
    "clean_username",
    "is_valid_profile_url",
    "calculate_engagement_rate",
    # Instagram
    "InstagramDiscovery",
    "InstagramAPI高iscovery",
    # YouTube
    "YouTubeDiscovery",
    "YouTubeTrendingDiscovery",
    # TikTok
    "TikTokDiscovery",
    "TikTokAPIDiscovery",
    # Directories
    "CollabstrDiscovery",
    "AspireDiscovery",
    "GrinDiscovery",
    "CreatorNewsletterDiscovery",
    "DirectoryManager",
    # Manager
    "EnhancedDiscoveryManager",
    "DiscoveryConfig",
    "run_discovery",
    "DiscoveryManager",
]