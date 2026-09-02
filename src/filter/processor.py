import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from src.core.config import get_settings
from src.core.models import (
    InfluencerBase,
    Niche,
    Platform,
    FilterResult,
    FilterRequest,
)
from src.filter.criteria import (
    FilterCriteria,
    FilterReason,
    CompositeFilter,
    EngagementCalculator,
)
from src.filter.classifier import NicheClassifier, ClassificationResult

logger = logging.getLogger(__name__)


@dataclass
class ProcessorConfig:
    """Configuration for the filter processor."""
    criteria: FilterCriteria
    classify_niches: bool = True
    calculate_engagement: bool = True
    min_confidence: float = 0.3
    deduplicate: bool = True


@dataclass
class ProcessingResult:
    """Complete result of filter processing."""
    filter_result: FilterResult
    classifications: List[ClassificationResult]
    passed_influencers: List[InfluencerBase]
    processing_time: float
    timestamp: datetime = datetime.utcnow()


class FilterProcessor:
    """
    Main filter processor that orchestrates the filtering pipeline.
    """

    def __init__(self, config: Optional[ProcessorConfig] = None):
        self.settings = get_settings()

        if config:
            self.config = config
        else:
            self.config = ProcessorConfig(
                criteria=FilterCriteria.from_settings(),
                classify_niches=True,
                calculate_engagement=True,
                min_confidence=0.3,
            )

        self.composite_filter = CompositeFilter(self.config.criteria)
        self.niche_classifier = NicheClassifier(use_ml=False)
        self.engagement_calculator = EngagementCalculator()

        self.stats = {
            "total_processed": 0,
            "total_passed": 0,
            "total_filtered": 0,
            "by_reason": {},
            "by_niche": {},
        }

    def process(
        self,
        influencers: List[InfluencerBase],
        request: Optional[FilterRequest] = None,
    ) -> ProcessingResult:
        """
        Process influencers through the complete filter pipeline.

        Args:
            influencers: List of influencers to filter
            request: Optional filter request to override config

        Returns:
            ProcessingResult with filtered influencers and statistics
        """
        import time
        start_time = time.time()

        if request:
            criteria = FilterCriteria.from_request(request)
            self.composite_filter = CompositeFilter(criteria)
            self.config.criteria = criteria

        logger.info(f"Processing {len(influencers)} influencers through filter pipeline")

        if self.config.deduplicate:
            influencers = self._deduplicate(influencers)
            logger.info(f"After deduplication: {len(influencers)} influencers")

        if self.config.calculate_engagement:
            influencers = self._calculate_engagement(influencers)

        filter_result = self.composite_filter.filter(
            influencers,
            calculate_engagement=self.config.calculate_engagement,
        )

        passed_influencers = self._get_passed_influencers(influencers, filter_result)

        classifications = []
        if self.config.classify_niches and passed_influencers:
            classifications = self.niche_classifier.classify_batch(passed_influencers)

            self.niche_classifier.apply_classifications(passed_influencers)

            confident_influencers = []
            for inf, cls in zip(passed_influencers, classifications):
                if cls.confidence >= self.config.min_confidence:
                    confident_influencers.append(inf)
                else:
                    inf.raw_data["low_niche_confidence"] = True
                    confident_influencers.append(inf)

            passed_influencers = confident_influencers

        self._update_stats(filter_result, classifications)

        processing_time = time.time() - start_time

        logger.info(
            f"Filter processing complete: {filter_result.passed_count}/{filter_result.input_count} passed "
            f"({processing_time:.2f}s)"
        )

        return ProcessingResult(
            filter_result=filter_result,
            classifications=classifications,
            passed_influencers=passed_influencers,
            processing_time=processing_time,
        )

    def _deduplicate(self, influencers: List[InfluencerBase]) -> List[InfluencerBase]:
        """Remove duplicates by username + platform."""
        seen = set()
        unique = []

        for inf in influencers:
            key = (inf.username.lower(), inf.platform)
            if key not in seen:
                seen.add(key)
                unique.append(inf)
            else:
                logger.debug(f"Duplicate removed: @{inf.username} on {inf.platform.value}")

        return unique

    def _calculate_engagement(self, influencers: List[InfluencerBase]) -> List[InfluencerBase]:
        """Calculate engagement metrics for all influencers."""
        for inf in influencers:
            metrics = self.engagement_calculator.calculate_from_raw_data(inf)
            inf.raw_data["calculated_engagement"] = metrics

            inf.raw_data["engagement_rate"] = metrics["engagement_rate"]
            inf.raw_data["engagement_rate_percent"] = metrics["engagement_rate_percent"]
            inf.raw_data["avg_likes"] = metrics["avg_likes"]
            inf.raw_data["avg_comments"] = metrics["avg_comments"]

        return influencers

    def _get_passed_influencers(
        self,
        influencers: List[InfluencerBase],
        filter_result: FilterResult,) -> List[InfluencerBase]:
        """Get list of influencers that passed all filters."""
        passed = []
        for inf in influencers:
            if self.composite_filter.criteria_filter.passes(inf):
                if self.config.criteria.target_niches:
                    matches = any(
                        self.composite_filter.niche_filter.matches_niche(inf, niche)
                        for niche in self.config.criteria.target_niches
                    )
                    if not matches:
                        continue

                if not self.composite_filter.quality_filter.passes(inf):
                    continue

                engagement = inf.raw_data.get("calculated_engagement", {})
                if engagement.get("engagement_rate", 0) < self.config.criteria.min_engagement_rate:
                    continue

                passed.append(inf)

        return passed

    def _update_stats(
        self,
        filter_result: FilterResult,
        classifications: List[ClassificationResult],
    ) -> None:
        """Update processing statistics."""
        self.stats["total_processed"] += filter_result.input_count
        self.stats["total_passed"] += filter_result.passed_count
        self.stats["total_filtered"] += filter_result.filtered_count

        for reason, count in filter_result.filtered_reasons.items():
            self.stats["by_reason"][reason] = self.stats["by_reason"].get(reason, 0) + count

        for niche, count in filter_result.classified_niches.items():
            niche_key = niche.value if isinstance(niche, Niche) else str(niche)
            self.stats["by_niche"][niche_key] = self.stats["by_niche"].get(niche_key, 0) + count

    def get_stats(self) -> Dict[str, Any]:
        """Get processing statistics."""
        return self.stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self.stats = {
            "total_processed": 0,
            "total_passed": 0,
            "total_filtered": 0,
            "by_reason": {},
            "by_niche": {},
        }


class BatchFilterProcessor:
    """
    Process large batches of influencers in chunks.
    Useful for memory efficiency with large datasets.
    """

    def __init__(self, processor: FilterProcessor, batch_size: int = 100):
        self.processor = processor
        self.batch_size = batch_size

    def process_batches(
        self,
        influencers: List[InfluencerBase],
        request: Optional[FilterRequest] = None,) -> ProcessingResult:
        """Process influencers in batches and combine results."""
        all_passed = []
        all_classifications = []
        combined_filter_result = None
        total_time = 0.0

        for i in range(0, len(influencers), self.batch_size):
            batch = influencers[i:i + self.batch_size]
            logger.info(f"Processing batch {i//self.batch_size + 1}/{(len(influencers) + self.batch_size - 1)//self.batch_size}")

            result = self.processor.process(batch, request)

            all_passed.extend(result.passed_influencers)
            all_classifications.extend(result.classifications)
            total_time += result.processing_time

            if combined_filter_result is None:
                combined_filter_result = result.filter_result
            else:
                combined_filter_result = self._combine_filter_results(
                    combined_filter_result,
                    result.filter_result,
                )

        return ProcessingResult(
            filter_result=combined_filter_result,
            classifications=all_classifications,
            passed_influencers=all_passed,
            processing_time=total_time,
        )

    def _combine_filter_results(
        self,
        result1: FilterResult,
        result2: FilterResult,) -> FilterResult:
        """Combine two filter results."""
        combined_reasons = {}
        for d in [result1.filtered_reasons, result2.filtered_reasons]:
            for k, v in d.items():
                combined_reasons[k] = combined_reasons.get(k, 0) + v

        combined_niches = {}
        for d in [result1.classified_niches, result2.classified_niches]:
            for k, v in d.items():
                key = k.value if isinstance(k, Niche) else k
                combined_niches[key] = combined_niches.get(key, 0) + v

        return FilterResult(
            input_count=result1.input_count + result2.input_count,
            passed_count=result1.passed_count + result2.passed_count,
            filtered_count=result1.filtered_count + result2.filtered_count,
            filtered_reasons=combined_reasons,
            classified_niches=combined_niches,
        )


def create_processor(
    min_followers: int = 5000,
    max_followers: int = 100000,
    min_engagement_rate: float = 0.02,
    target_niches: Optional[List[Niche]] = None,
    require_contact: bool = False,) -> FilterProcessor:
    """Factory function to create a filter processor with custom criteria."""
    criteria = FilterCriteria(
        min_followers=min_followers,
        max_followers=max_followers,
        min_engagement_rate=min_engagement_rate,
        target_niches=target_niches,
        require_contact_info=require_contact,
    )

    config = ProcessorConfig(criteria=criteria)
    return FilterProcessor(config)


__all__ = [
    "ProcessorConfig",
    "ProcessingResult",
    "FilterProcessor",
    "BatchFilterProcessor",
    "create_processor",
]
