"""
Enrichment Manager - Orchestrates all enrichment processes.
Coordinates contact, content, and cross-platform enrichment for influencers.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any
from src.core.config import get_settings, get_niche_keywords
from src.core.models import (
    InfluencerBase,
    EnrichedProfile,
    Niche,
    Platform,
    EngagementMetrics,
    ContactInfo,
    ContentAnalysis,
    CrossPlatformPresence,
)
from src.enrichment.base import EnrichmentBase
from src.enrichment.contact import ContactEnricher, get_contact_enricher
from src.enrichment.content import ContentEnricher, get_content_enricher
from src.enrichment.cross_platform import CrossPlatformEnricher
from src.filter.criteria import EngagementCalculator

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentConfig:
    """Configuration for enrichment run."""
    extract_emails: bool = True
    analyze_recent_posts: int = 10
    check_cross_platform: bool = True
    resolve_link_in_bio: bool = True
    max_concurrent: int = 5
    request_timeout: int = 30


@dataclass
class EnrichmentStats:
    """Statistics for enrichment run."""
    total_processed: int = 0
    successful: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def success_rate(self) -> float:
        if self.total_processed == 0:
            return 0.0
        return self.successful / self.total_processed * 100


class EnrichmentManager:
    """
    Main enrichment orchestrator.
    Runs contact, content, and cross-platform enrichment in parallel.
    """

    def __init__(self, config: Optional[EnrichmentConfig] = None):
        self.config = config or EnrichmentConfig(
            extract_emails=get_settings().enrichment.extract_emails,
            analyze_recent_posts=get_settings().enrichment.analyze_recent_posts,
            check_cross_platform=get_settings().enrichment.check_cross_platform,
            resolve_link_in_bio=get_settings().enrichment.resolve_link_in_bio,
            max_concurrent=get_settings().discovery.max_concurrent,
            request_timeout=get_settings().discovery.request_timeout,
        )

        self.niche_keywords = get_niche_keywords()
        self.engagement_calculator = EngagementCalculator()
        self.stats = EnrichmentStats()
        self._semaphore: Optional[asyncio.Semaphore] = None

        self.contact_enrichers: Dict[Platform, ContactEnricher] = {}
        self.content_enrichers: Dict[Platform, ContentEnricher] = {}
        self.cross_platform_enricher = CrossPlatformEnricher()

    async def enrich_batch(
        self,
        influencers: List[InfluencerBase],
        classify_niches: bool = True,
    ) -> List[EnrichedProfile]:
        """
        Enrich a batch of influencers.

        Args:
            influencers: List of influencers to enrich
            classify_niches: Whether to classify niches for each influencer

        Returns:
            List of EnrichedProfile objects
        """
        self.stats = EnrichmentStats(
            total_processed=len(influencers),
            start_time=datetime.utcnow(),
        )
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)

        logger.info(f"Starting enrichment for {len(influencers)} influencers")

        tasks = [
            self._enrich_single(influencer, classify_niches)
            for influencer in influencers
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        enriched_profiles = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.stats.failed += 1
                error_msg = f"Enrichment failed for {influencers[i].username}: {result}"
                self.stats.errors.append(error_msg)
                logger.error(error_msg)

                enriched_profiles.append(self._create_error_profile(influencers[i], str(result)))
            elif isinstance(result, EnrichedProfile):
                self.stats.successful += 1
                enriched_profiles.append(result)

        self.stats.end_time = datetime.utcnow()

        logger.info(
            f"Enrichment complete: {self.stats.successful}/{self.stats.total_processed} successful "
            f"({self.stats.duration_seconds:.2f}s)"
        )

        return enriched_profiles

    async def _enrich_single(
        self,
        influencer: InfluencerBase,
        classify_niche: bool,
    ) -> EnrichedProfile:
        """Enrich a single influencer with all enrichment types."""
        async with self._semaphore:
            enrichment_errors = []

            contact_task = None
            content_task = None
            cross_platform_task = None

            if self.config.extract_emails:
                contact_enricher = self._get_contact_enricher(influencer.platform)
                contact_task = contact_enricher.enrich_contact(influencer)

            if self.config.analyze_recent_posts > 0:
                content_enricher = self._get_content_enricher(influencer.platform)
                content_task = content_enricher.enrich_content(
                    influencer,
                    self.config.analyze_recent_posts
                )

            if self.config.check_cross_platform:
                cross_platform_task = self.cross_platform_enricher.enrich_cross_platform(influencer)

            contact_info = ContactInfo()
            content_analysis = ContentAnalysis()
            cross_platform = CrossPlatformPresence()

            if contact_task:
                try:
                    contact_info = await contact_task
                except Exception as e:
                    enrichment_errors.append(f"Contact: {e}")
                    logger.warning(f"Contact enrichment failed for @{influencer.username}: {e}")

            if content_task:
                try:
                    content_analysis = await content_task
                except Exception as e:
                    enrichment_errors.append(f"Content: {e}")
                    logger.warning(f"Content enrichment failed for @{influencer.username}: {e}")

            if cross_platform_task:
                try:
                    cross_platform = await cross_platform_task
                except Exception as e:
                    enrichment_errors.append(f"Cross-platform: {e}")
                    logger.warning(f"Cross-platform enrichment failed for @{influencer.username}: {e}")

            engagement = self._calculate_engagement(influencer, content_analysis)

            niche = Niche.LIFESTYLE
            niche_confidence = 0.0
            if classify_niche:
                niche, niche_confidence = self._classify_niche(influencer, content_analysis)

            profile = EnrichedProfile(
                influencer=influencer,
                niche=niche,
                niche_confidence=niche_confidence,
                engagement=engagement,
                contact=contact_info,
                content=content_analysis,
                cross_platform=cross_platform,
                enrichment_errors=enrichment_errors,
            )

            return profile

    def _get_contact_enricher(self, platform: Platform) -> ContactEnricher:
        """Get or create contact enricher for platform."""
        if platform not in self.contact_enrichers:
            self.contact_enrichers[platform] = get_contact_enricher(
                platform,
                timeout=self.config.request_timeout,
            )
        return self.contact_enrichers[platform]

    def _get_content_enricher(self, platform: Platform) -> ContentEnricher:
        """Get or create content enricher for platform."""
        if platform not in self.content_enrichers:
            self.content_enrichers[platform] = get_content_enricher(
                platform,
                timeout=self.config.request_timeout,
            )
        return self.content_enrichers[platform]

    def _calculate_engagement(
        self,
        influencer: InfluencerBase,
        content_analysis: ContentAnalysis,) -> EngagementMetrics:
        """Calculate engagement metrics from available data."""
        raw_engagement = influencer.raw_data.get("calculated_engagement", {})

        if raw_engagement:
            return EngagementMetrics(
                avg_likes=raw_engagement.get("avg_likes", 0),
                avg_comments=raw_engagement.get("avg_comments", 0),
                avg_shares=raw_engagement.get("avg_shares", 0),
                avg_views=raw_engagement.get("avg_views", 0),
                engagement_rate=raw_engagement.get("engagement_rate", 0),
                engagement_rate_percent=raw_engagement.get("engagement_rate_percent", 0),
                post_frequency_per_week=self._estimate_post_frequency(content_analysis.posting_schedule),
                recent_posts_analyzed=content_analysis.posts_analyzed,
                calculated_at=datetime.utcnow(),
            )

        metrics = self.engagement_calculator.calculate_from_raw_data(influencer)

        return EngagementMetrics(
            avg_likes=metrics["avg_likes"],
            avg_comments=metrics["avg_comments"],
            avg_shares=metrics["avg_shares"],
            avg_views=metrics["avg_views"],
            engagement_rate=metrics["engagement_rate"],
            engagement_rate_percent=metrics["engagement_rate_percent"],
            post_frequency_per_week=self._estimate_post_frequency(content_analysis.posting_schedule),
            recent_posts_analyzed=content_analysis.posts_analyzed,
            calculated_at=datetime.utcnow(),
        )

    def _estimate_post_frequency(self, schedule: Optional[str]) -> float:
        """Estimate posts per week from schedule string."""
        if not schedule:
            return 0.0

        schedule_lower = schedule.lower()
        if "daily" in schedule_lower:
            return 7.0
        elif "3x" in schedule_lower or "3 times" in schedule_lower:
            return 3.0
        elif "weekly" in schedule_lower or "1x" in schedule_lower:
            return 1.0
        elif "2" in schedule_lower:
            return 2.0
        elif "irregular" in schedule_lower:
            return 0.5
        return 2.0  # Default

    def _classify_niche(
        self,
        influencer: InfluencerBase,
        content_analysis: ContentAnalysis,
    ) -> tuple[Niche, float]:
        """Classify influencer niche based on bio and content."""
        if "classified_niche" in influencer.raw_data:
            try:
                niche = Niche(influencer.raw_data["classified_niche"])
                confidence = influencer.raw_data.get("niche_confidence", 0.5)
                return niche, confidence
            except ValueError:
                pass

        text_parts = [
            influencer.username,
            influencer.display_name or "",
            influencer.bio or "",
        ]

        text_parts.extend(content_analysis.primary_topics)
        text_parts.extend(content_analysis.content_pillars)

        full_text = " ".join(text_parts).lower()

        scores: Dict[Niche, float] = {}
        for niche in Niche:
            keywords = self.niche_keywords.get_keywords(niche)
            hashtags = self.niche_keywords.get_hashtags(niche)
            all_terms = keywords + hashtags

            score = 0.0
            for term in all_terms:
                if term.lower() in full_text:
                    score += 1.0 + (len(term) / 20.0)

            if all_terms:
                scores[niche] = score / len(all_terms) * 100
            else:
                scores[niche] = 0.0

        if scores:
            best_niche = max(scores, key=scores.get)
            best_score = scores[best_niche]

            sorted_scores = sorted(scores.values(), reverse=True)
            if len(sorted_scores) > 1 and sorted_scores[1] > 0:
                confidence = min(1.0, (sorted_scores[0] - sorted_scores[1]) / sorted_scores[0] + 0.5)
            else:
                confidence = min(1.0, best_score / 10.0)

            if best_score > 0:
                confidence = max(confidence, 0.3)
            else:
                confidence = 0.0
                best_niche = Niche.LIFESTYLE
        else:
            best_niche = Niche.LIFESTYLE
            confidence = 0.0

        return best_niche, confidence

    def _create_error_profile(self, influencer: InfluencerBase, error: str) -> EnrichedProfile:
        """Create minimal enriched profile for failed enrichment."""
        return EnrichedProfile(
            influencer=influencer,
            niche=Niche.LIFESTYLE,
            niche_confidence=0.0,
            engagement=EngagementMetrics(),
            contact=ContactInfo(),
            content=ContentAnalysis(),
            cross_platform=CrossPlatformPresence(),
            enrichment_errors=[error],
        )

    async def close(self) -> None:
        """Close all enricher clients."""
        for enricher in self.contact_enrichers.values():
            await enricher.close()
        for enricher in self.content_enrichers.values():
            await enricher.close()
        await self.cross_platform_enricher.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get enrichment statistics."""
        return {
            "total_processed": self.stats.total_processed,
            "successful": self.stats.successful,
            "failed": self.stats.failed,
            "success_rate": self.stats.success_rate,
            "duration_seconds": self.stats.duration_seconds,
            "errors": self.stats.errors,
        }


async def enrich_influencers(
    influencers: List[InfluencerBase],
    config: Optional[EnrichmentConfig] = None,
    classify_niches: bool = True,) -> List[EnrichedProfile]:
    """Convenience function to enrich influencers."""
    manager = EnrichmentManager(config)
    try:
        return await manager.enrich_batch(influencers, classify_niches)
    finally:
        await manager.close()


# Export
__all__ = [
    "EnrichmentConfig",
    "EnrichmentStats",
    "EnrichmentManager",
    "enrich_influencers",
]