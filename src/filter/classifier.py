"""
Niche classifier for influencers.
Uses keyword matching and optional ML-based classification.
"""

import logging
import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import Counter
from src.core.config import get_settings, get_niche_keywords
from src.core.models import InfluencerBase, Niche

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Result of niche classification."""
    niche: Niche
    confidence: float
    matched_keywords: List[str]
    all_scores: Dict[Niche, float]


class KeywordClassifier:
    """Keyword-based niche classifier."""

    def __init__(self):
        self.niche_keywords = get_niche_keywords()
        self._compiled_patterns: Dict[Niche, List[re.Pattern]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for each niche's keywords."""
        for niche in Niche:
            keywords = self.niche_keywords.get_keywords(niche)
            patterns = []
            for kw in keywords:
                pattern = re.compile(rf"\b{re.escape(kw.lower())}\b", re.IGNORECASE)
                patterns.append(pattern)
            self._compiled_patterns[niche] = patterns

    def classify(self, influencer: InfluencerBase) -> ClassificationResult:
        """Classify influencer into a niche."""
        text_parts = [
            influencer.username,
            influencer.display_name or "",
            influencer.bio or "",
        ]

        for key, value in influencer.raw_data.items():
            if isinstance(value, str):
                text_parts.append(value)
            elif isinstance(value, list):
                text_parts.extend(str(v) for v in value if isinstance(v, str))

        full_text = " ".join(text_parts).lower()

        scores: Dict[Niche, float] = {}
        matched_keywords: Dict[Niche, List[str]] = {}

        for niche in Niche:
            keywords = self.niche_keywords.get_keywords(niche)
            matches = []

            for keyword in keywords:
                if keyword.lower() in full_text:
                    matches.append(keyword)

            score = 0.0
            for match in matches:
                score += 1.0 + (len(match) / 20.0)

            total_keywords = len(keywords)
            if total_keywords > 0:
                normalized_score = score / total_keywords * 100  
            else:
                normalized_score = 0.0

            scores[niche] = normalized_score
            matched_keywords[niche] = matches

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
            matched_keywords[best_niche] = []

        return ClassificationResult(
            niche=best_niche,
            confidence=confidence,
            matched_keywords=matched_keywords.get(best_niche, []),
            all_scores=scores,
        )

    def classify_batch(self, influencers: List[InfluencerBase]) -> List[ClassificationResult]:
        """Classify multiple influencers."""
        return [self.classify(inf) for inf in influencers]


class MLClassifier:
    """
    ML-based classifier placeholder.
    In production, this would use a trained model (e.g., scikit-learn, transformers).
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self.model = None
        self.vectorizer = None
        self._load_model()

    def _load_model(self) -> None:
        """Load trained model if available."""
        if self.model_path:
            try:
                import joblib
                self.model = joblib.load(self.model_path)
                logger.info(f"Loaded ML classifier from {self.model_path}")
            except Exception as e:
                logger.warning(f"Failed to load ML model: {e}")

    def train(self, training_data: List[Tuple[str, Niche]]) -> None:
        """Train a simple classifier (placeholder)."""
        logger.info(f"Training ML classifier on {len(training_data)} samples")

    def classify(self, influencer: InfluencerBase) -> ClassificationResult:
        """Classify using ML model."""
        if not self.model:
            return KeywordClassifier().classify(influencer)

        text = self._extract_features(influencer)

        return KeywordClassifier().classify(influencer)

    def _extract_features(self, influencer: InfluencerBase) -> str:
        """Extract text features for ML model."""
        return " ".join([
            influencer.username,
            influencer.display_name or "",
            influencer.bio or "",
        ])


class HybridClassifier:
    """Combines keyword and ML classification."""

    def __init__(self, ml_model_path: Optional[str] = None):
        self.keyword_classifier = KeywordClassifier()
        self.ml_classifier = MLClassifier(ml_model_path)
        self.use_ml = ml_model_path is not None

    def classify(self, influencer: InfluencerBase) -> ClassificationResult:
        """Classify using hybrid approach."""
        keyword_result = self.keyword_classifier.classify(influencer)

        if not self.use_ml:
            return keyword_result

        ml_result = self.ml_classifier.classify(influencer)

        
        if keyword_result.niche == ml_result.niche:
            combined_confidence = min(1.0, (keyword_result.confidence + ml_result.confidence) / 2 + 0.1)
            return ClassificationResult(
                niche=keyword_result.niche,
                confidence=combined_confidence,
                matched_keywords=keyword_result.matched_keywords,
                all_scores=keyword_result.all_scores,
            )

        if keyword_result.confidence >= ml_result.confidence:
            return ClassificationResult(
                niche=keyword_result.niche,
                confidence=max(0.3, keyword_result.confidence - 0.1),
                matched_keywords=keyword_result.matched_keywords,
                all_scores=keyword_result.all_scores,
            )
        else:
            return ClassificationResult(
                niche=ml_result.niche,
                confidence=max(0.3, ml_result.confidence - 0.1),
                matched_keywords=keyword_result.matched_keywords, 
                all_scores=keyword_result.all_scores,
            )

    def classify_batch(self, influencers: List[InfluencerBase]) -> List[ClassificationResult]:
        """Classify multiple influencers."""
        return [self.classify(inf) for inf in influencers]


class NicheClassifier:
    """Main classifier interface."""

    def __init__(self, use_ml: bool = False, ml_model_path: Optional[str] = None):
        if use_ml and ml_model_path:
            self.classifier = HybridClassifier(ml_model_path)
        else:
            self.classifier = KeywordClassifier()

    def classify(self, influencer: InfluencerBase) -> ClassificationResult:
        """Classify a single influencer."""
        return self.classifier.classify(influencer)

    def classify_batch(self, influencers: List[InfluencerBase]) -> List[ClassificationResult]:
        """Classify multiple influencers."""
        return self.classifier.classify_batch(influencers)

    def apply_classifications(
        self,
        influencers: List[InfluencerBase],
    ) -> List[InfluencerBase]:
        """Apply classifications to influencers (modifies in place)."""
        results = self.classify_batch(influencers)

        for influencer, result in zip(influencers, results):
            influencer.raw_data["classified_niche"] = result.niche.value
            influencer.raw_data["niche_confidence"] = result.confidence
            influencer.raw_data["matched_keywords"] = result.matched_keywords
            influencer.raw_data["all_niche_scores"] = {
                n.value: s for n, s in result.all_scores.items()
            }

        return influencers


def get_classifier(use_ml: bool = False) -> NicheClassifier:
    """Get a classifier instance."""
    return NicheClassifier(use_ml=use_ml)


__all__ = [
    "ClassificationResult",
    "KeywordClassifier",
    "MLClassifier",
    "HybridClassifier",
    "NicheClassifier",
    "get_classifier",
]