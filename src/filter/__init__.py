from src.filter.criteria import (
    FilterCriteria,
    FilterReason,
    CriteriaFilter,
    EngagementCalculator,
    NicheFilter,
    QualityFilter,
    CompositeFilter,
)

from src.filter.classifier import (
    ClassificationResult,
    KeywordClassifier,
    MLClassifier,
    HybridClassifier,
    NicheClassifier,
    get_classifier,
)

from src.filter.processor import (
    ProcessorConfig,
    ProcessingResult,
    FilterProcessor,
    BatchFilterProcessor,
    create_processor,
)

__all__ = [
    # Criteria
    "FilterCriteria",
    "FilterReason",
    "CriteriaFilter",
    "EngagementCalculator",
    "NicheFilter",
    "QualityFilter",
    "CompositeFilter",
    # Classifier
    "ClassificationResult",
    "KeywordClassifier",
    "MLClassifier",
    "HybridClassifier",
    "NicheClassifier",
    "get_classifier",
    # Processor
    "ProcessorConfig",
    "ProcessingResult",
    "FilterProcessor",
    "BatchFilterProcessor",
    "create_processor",
]
