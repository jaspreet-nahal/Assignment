import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from enum import Enum
from src.core.config import get_settings
from src.core.models import (
    InfluencerBase,
    Niche,
    Platform,
    InfluencerTier,
    FilterResult,
    FilterRequest,
)
from src.discovery.base import calculate_engagement_rate

logger = logging.getLogger(__name__)


class FilterReason(str, Enum):
    """Reasons for filtering out an influencer."""
    FOLLOWERS_TOO_LOW = "followers_too_low"
    FOLLOWERS_TOO_HIGH = "followers_too_high"
    ENGAGEMENT_TOO_LOW = "engagement_too_low"
    INSUFFICIENT_POSTS = "insufficient_posts"
    NO_CONTACT_INFO = "no_contact_info"
    NICHE_MISMATCH = "niche_mismatch"
    PRIVATE_ACCOUNT = "private_account"
    VERIFIED_REQUIRED = "verified_required"
    PLATFORM_EXCLUDED = "platform_excluded"
    LOW_QUALITY = "low_quality"


@dataclass
class FilterCriteria:
    """Configurable filter criteria."""
    min_followers: int = 5000
    max_followers: int = 100000
    min_engagement_rate: float = 0.02
    min_posts: int = 10
    require_contact_info: bool = False
    require_verified: bool = False
    allowed_platforms: Optional[List[Platform]] = None
    excluded_platforms: List[Platform] = field(default_factory=list)
    target_niches: Optional[List[Niche]] = None
    excluded_niches: List[Niche] = field(default_factory=list)
    min_quality_score: float = 0.0

    @classmethod
    def from_request(cls, request: FilterRequest) -> "FilterCriteria":
        """Create criteria from filter request."""
        return cls(
            min_followers=request.min_followers,
            max_followers=request.max_followers,
            min_engagement_rate=request.min_engagement_rate,
            min_posts=request.min_posts,
            require_contact_info=request.require_contact,
            target_niches=request.niches,
        )

    @classmethod
    def from_settings(cls) -> "FilterCriteria":
        """Create criteria from application settings."""
        settings = get_settings()
        return cls(
            min_followers=settings.filter.min_followers,
            max_followers=settings.filter.max_followers,
            min_engagement_rate=settings.filter.min_engagement_rate,
            min_posts=settings.filter.min_posts,
            require_contact_info=settings.filter.require_contact_info,
        )


class CriteriaFilter:
    """Applies filter criteria to influencers."""

    def __init__(self, criteria: Optional[FilterCriteria] = None):
        self.criteria = criteria or FilterCriteria.from_settings()
        self._custom_filters: List[Callable[[InfluencerBase], Optional[FilterReason]]] = []

    def add_custom_filter(self, filter_func: Callable[[InfluencerBase], Optional[FilterReason]]) -> None:
        """Add a custom filter function."""
        self._custom_filters.append(filter_func)

    def check_influencer(self, influencer: InfluencerBase) -> List[FilterReason]:
        """Check influencer against all criteria. Returns list of failed reasons."""
        reasons = []

        if influencer.follower_count < self.criteria.min_followers:
            reasons.append(FilterReason.FOLLOWERS_TOO_LOW)
        if influencer.follower_count > self.criteria.max_followers:
            reasons.append(FilterReason.FOLLOWERS_TOO_HIGH)

        if influencer.post_count is not None and influencer.post_count < self.criteria.min_posts:
            reasons.append(FilterReason.INSUFFICIENT_POSTS)

        if self.criteria.allowed_platforms and influencer.platform not in self.criteria.allowed_platforms:
            reasons.append(FilterReason.PLATFORM_EXCLUDED)
        if influencer.platform in self.criteria.excluded_platforms:
            reasons.append(FilterReason.PLATFORM_EXCLUDED)

        if self.criteria.require_verified and not influencer.verified:
            reasons.append(FilterReason.VERIFIED_REQUIRED)

        is_private = influencer.raw_data.get("is_private", False)
        if is_private:
            reasons.append(FilterReason.PRIVATE_ACCOUNT)

        for custom_filter in self._custom_filters:
            reason = custom_filter(influencer)
            if reason:
                reasons.append(reason)

        return reasons

    def passes(self, influencer: InfluencerBase) -> bool:
        """Check if influencer passes all criteria."""
        return len(self.check_influencer(influencer)) == 0

    def filter_batch(self, influencers: List[InfluencerBase]) -> FilterResult:
        """Filter a batch of influencers and return result."""
        passed = []
        filtered_count = 0
        filtered_reasons: Dict[str, int] = {}

        for inf in influencers:
            reasons = self.check_influencer(inf)
            if not reasons:
                passed.append(inf)
            else:
                filtered_count += 1
                for reason in reasons:
                    filtered_reasons[reason.value] = filtered_reasons.get(reason.value, 0) + 1

        return FilterResult(
            input_count=len(influencers),
            passed_count=len(passed),
            filtered_count=filtered_count,
            filtered_reasons=filtered_reasons,
        )


class EngagementCalculator:
    """Calculates engagement metrics from available data."""

    @staticmethod
    def calculate_from_raw_data(influencer: InfluencerBase) -> Dict[str, float]:
        """Calculate engagement metrics from raw data."""
        raw = influencer.raw_data

        avg_likes = raw.get("avg_likes", 0)
        avg_comments = raw.get("avg_comments", 0)
        avg_shares = raw.get("avg_shares", 0)
        avg_views = raw.get("avg_views", 0)

        if avg_likes == 0 and avg_comments == 0:
            avg_likes, avg_comments, avg_shares, avg_views = EngagementCalculator._estimate_engagement(
                influencer.platform,
                influencer.follower_count,
                influencer.post_count or 0,
            )

        engagement_rate = calculate_engagement_rate(
            avg_likes, avg_comments, avg_shares, influencer.follower_count
        )

        return {
            "avg_likes": avg_likes,
            "avg_comments": avg_comments,
            "avg_shares": avg_shares,
            "avg_views": avg_views,
            "engagement_rate": engagement_rate,
            "engagement_rate_percent": engagement_rate * 100,
        }

    @staticmethod
    def _estimate_engagement(
        platform: Platform,
        follower_count: int,
        post_count: int,
    ) -> tuple:
        """Estimate engagement based on platform benchmarks."""
        platform_benchmarks = {
            Platform.INSTAGRAM: {"like_rate": 0.015, "comment_rate": 0.003, "share_rate": 0.001},
            Platform.YOUTUBE: {"like_rate": 0.005, "comment_rate": 0.001, "share_rate": 0.0005},
            Platform.TIKTOK: {"like_rate": 0.03, "comment_rate": 0.005, "share_rate": 0.01},
            Platform.TWITTER: {"like_rate": 0.005, "comment_rate": 0.001, "share_rate": 0.002},
        }

        benchmark = platform_benchmarks.get(platform, platform_benchmarks[Platform.INSTAGRAM])

        if follower_count < 10000:
            multiplier = 1.5
        elif follower_count < 50000:
            multiplier = 1.2
        else:
            multiplier = 1.0

        avg_likes = follower_count * benchmark["like_rate"] * multiplier
        avg_comments = follower_count * benchmark["comment_rate"] * multiplier
        avg_shares = follower_count * benchmark["share_rate"] * multiplier
        avg_views = follower_count * 0.1  # Rough estimate

        return (avg_likes, avg_comments, avg_shares, avg_views)


class NicheFilter:
    """Filters influencers by niche relevance."""

    def __init__(self, target_niches: Optional[List[Niche]] = None):
        self.target_niches = target_niches or []
        self.niche_keywords = self._load_niche_keywords()

    def _load_niche_keywords(self) -> Dict[Niche, List[str]]:
        """Load niche keywords for matching."""
        return {
            Niche.FITNESS: ["fitness", "workout", "gym", "training", "health", "wellness", "bodybuilding", "yoga", "running", "nutrition"],
            Niche.FINTECH: ["finance", "investing", "money", "crypto", "trading", "wealth", "stocks", "bitcoin", "personal finance"],
            Niche.BEAUTY: ["beauty", "makeup", "skincare", "cosmetics", "mua", "skincareroutine", "beautytips"],
            Niche.FASHION: ["fashion", "style", "outfit", "ootd", "streetwear", "fashionblogger", "stylist"],
            Niche.CRYPTO: ["crypto", "bitcoin", "ethereum", "defi", "nft", "web3", "blockchain", "trading"],
            Niche.PARENTING: ["parenting", "mom", "dad", "motherhood", "fatherhood", "baby", "kids", "family"],
            Niche.GAMING: ["gaming", "gamer", "esports", "twitch", "streamer", "gameplay", "videogames"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "routine", "productivity", "wellness", "travel", "home"],
            Niche.TECHNOLOGY: ["tech", "programming", "coding", "developer", "software", "ai", "webdev", "startup"],
        }

    def matches_niche(self, influencer: InfluencerBase, niche: Niche) -> bool:
        """Check if influencer matches a specific niche."""
        keywords = self.niche_keywords.get(niche, [niche.value])

        searchable_text = " ".join([
            influencer.bio or "",
            influencer.display_name or "",
            influencer.username,
            " ".join(str(v) for v in influencer.raw_data.values() if isinstance(v, str)),
        ]).lower()

        return any(keyword.lower() in searchable_text for keyword in keywords)

    def get_matching_niches(self, influencer: InfluencerBase) -> List[Niche]:
        """Get all niches that match the influencer."""
        matches = []
        for niche in Niche:
            if self.matches_niche(influencer, niche):
                matches.append(niche)
        return matches

    def filter_by_niche(self, influencers: List[InfluencerBase]) -> List[InfluencerBase]:
        """Filter influencers to only those matching target niches."""
        if not self.target_niches:
            return influencers

        filtered = []
        for inf in influencers:
            if any(self.matches_niche(inf, niche) for niche in self.target_niches):
                filtered.append(inf)
        return filtered


class QualityFilter:
    """Filters influencers by content quality signals."""

    def __init__(self, min_score: float = 0.3):
        self.min_score = min_score

    def calculate_quality_score(self, influencer: InfluencerBase) -> float:
        """Calculate a quality score (0-1) for an influencer."""
        score = 0.0
        factors = 0

        if influencer.bio and len(influencer.bio) > 20:
            score += 0.2
        factors += 1

        if influencer.profile_image_url:
            score += 0.1
        factors += 1

        if influencer.external_url:
            score += 0.15
        factors += 1

        post_count = influencer.post_count or 0
        if post_count > 50:
            score += 0.2
        elif post_count > 20:
            score += 0.15
        elif post_count > 10:
            score += 0.1
        factors += 1

        if influencer.following_count and influencer.follower_count:
            ratio = influencer.following_count / influencer.follower_count
            if ratio < 0.5:
                score += 0.15
            elif ratio < 1.0:
                score += 0.1
        factors += 1

        if influencer.verified:
            score += 0.1
        factors += 1

        if not influencer.raw_data.get("is_private", False):
            score += 0.1
        factors += 1

        return score / factors if factors > 0 else 0.0

    def passes(self, influencer: InfluencerBase) -> bool:
        return self.calculate_quality_score(influencer) >= self.min_score


class CompositeFilter:
    """Combines multiple filters for comprehensive filtering."""

    def __init__(self, criteria: Optional[FilterCriteria] = None):
        self.criteria_filter = CriteriaFilter(criteria)
        self.niche_filter = NicheFilter(criteria.target_niches if criteria else None)
        self.quality_filter = QualityFilter(criteria.min_quality_score if criteria else 0.3)
        self.engagement_calculator = EngagementCalculator()

    def filter(
        self,
        influencers: List[InfluencerBase],
        calculate_engagement: bool = True,
    ) -> FilterResult:
        """Run all filters on influencers."""
        criteria_result = self.criteria_filter.filter_batch(influencers)
        passed = [inf for inf in influencers if self.criteria_filter.passes(inf)]

        if self.niche_filter.target_niches:
            passed = self.niche_filter.filter_by_niche(passed)

        passed = [inf for inf in passed if self.quality_filter.passes(inf)]

        if calculate_engagement:
            for inf in passed:
                metrics = self.engagement_calculator.calculate_from_raw_data(inf)
                inf.raw_data["calculated_engagement"] = metrics

                if metrics["engagement_rate"] < self.criteria_filter.criteria.min_engagement_rate:
                    inf.raw_data["low_engagement"] = True

        final_passed = []
        filtered_reasons = dict(criteria_result.filtered_reasons)

        for inf in passed:
            engagement = inf.raw_data.get("calculated_engagement", {})
            engagement_rate = engagement.get("engagement_rate", 0)

            if engagement_rate >= self.criteria_filter.criteria.min_engagement_rate:
                final_passed.append(inf)
            else:
                filtered_reasons[FilterReason.ENGAGEMENT_TOO_LOW.value] = \
                    filtered_reasons.get(FilterReason.ENGAGEMENT_TOO_LOW.value, 0) + 1

        classified_niches: Dict[Niche, int] = {}
        for inf in final_passed:
            matches = self.niche_filter.get_matching_niches(inf)
            for niche in matches:
                classified_niches[niche] = classified_niches.get(niche, 0) + 1

        return FilterResult(
            input_count=len(influencers),
            passed_count=len(final_passed),
            filtered_count=len(influencers) - len(final_passed),
            filtered_reasons=filtered_reasons,
            classified_niches=classified_niches,
        )


__all__ = [
    "FilterCriteria",
    "FilterReason",
    "CriteriaFilter",
    "EngagementCalculator",
    "NicheFilter",
    "QualityFilter",
    "CompositeFilter",
]
