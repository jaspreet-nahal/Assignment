import json
import re
import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from bs4 import BeautifulSoup
from src.core.models import InfluencerBase, ContentAnalysis, Platform, Niche
from src.enrichment.base import EnrichmentBase, detect_language, analyze_sentiment

logger = logging.getLogger(__name__)


class ContentEnricher(EnrichmentBase):
    """Analyzes influencer content for topics, quality, and brand safety."""

    def __init__(self, platform: Platform = Platform.INSTAGRAM, **kwargs):
        super().__init__(platform, **kwargs)

        self.unsafe_keywords = {
            "adult", "nsfw", "porn", "sex", "xxx", "onlyfans", "fansly",
            "gambling", "casino", "betting", "sportsbook",
            "drugs", "cocaine", "heroin", "meth", "steroids",
            "hate", "racist", "nazi", "terrorist", "violence",
            "scam", "fraud", "fake", "bot", "buy followers",
        }

        self.sponsored_keywords = {
            "ad", "sponsored", "partner", "partnership", "collab", "collaboration",
            "affiliate", "promo", "promotion", "gifted", "pr package", "pr gift",
            "brand ambassador", "ambassador", "sponsored by", "paid partnership",
            "#ad", "#sponsored", "#partner", "#collab", "#affiliate", "#gifted",
            "thank you @", "thanks @", "love this @", "obsessed with @",
        }

        self.topic_categories = {
            Niche.FITNESS: ["workout", "fitness", "gym", "training", "exercise", "health", "nutrition", "muscle", "strength", "cardio", "running", "yoga", "pilates", "bodybuilding", "crossfit"],
            Niche.FINTECH: ["finance", "investing", "money", "crypto", "trading", "stocks", "bitcoin", "ethereum", "defi", "wallet", "banking", "fintech", "wealth", "portfolio", "etf", "robinhood"],
            Niche.BEAUTY: ["beauty", "skincare", "makeup", "cosmetics", "routine", "serum", "moisturizer", "cleanser", "sunscreen", "retinol", "vitamin c", "foundation", "lipstick", "mascara", "sephora", "ulta"],
            Niche.FASHION: ["fashion", "style", "outfit", "ootd", "streetwear", "vintage", "thrift", "sustainable fashion", "shoes", "sneakers", "handbags", "accessories", "styling", "wardrobe"],
            Niche.CRYPTO: ["crypto", "bitcoin", "btc", "ethereum", "eth", "altcoin", "defi", "nft", "web3", "blockchain", "trading", "hodl", "staking", "wallet", "exchange", "binance", "coinbase"],
            Niche.PARENTING: ["parenting", "mom", "dad", "baby", "newborn", "toddler", "kids", "family", "pregnancy", "postpartum", "breastfeeding", "sleep training", "montessori", "gentle parenting"],
            Niche.GAMING: ["gaming", "gamer", "esports", "twitch", "streamer", "streaming", "playstation", "xbox", "nintendo", "switch", "fortnite", "valorant", "league of legends", "minecraft", "roblox"],
            Niche.LIFESTYLE: ["lifestyle", "vlog", "routine", "productivity", "wellness", "self care", "mental health", "mindfulness", "travel", "home decor", "interior design", "minimalism", "organization"],
            Niche.TECHNOLOGY: ["tech", "programming", "coding", "developer", "software", "ai", "machine learning", "python", "javascript", "react", "webdev", "startup", "saas", "devops", "cloud"],
        }

    async def enrich_content(self, influencer: InfluencerBase, post_count: int = 10) -> ContentAnalysis:
        """
        Main entry point for content enrichment.
        Analyzes recent posts for topics, quality, brand safety, etc.
        """
        if influencer.raw_data.get("mock", False):
            return self._generate_mock_content_analysis(influencer, post_count)

        posts_data = await self._fetch_recent_posts(influencer, post_count)

        if not posts_data:
            return ContentAnalysis(
                posts_analyzed=0,
                analyzed_at=datetime.utcnow(),
            )

        analysis = self._analyze_posts(posts_data, influencer)

        return ContentAnalysis(
            primary_topics=analysis["primary_topics"],
            content_pillars=analysis["content_pillars"],
            posting_schedule=analysis["posting_schedule"],
            content_quality_score=analysis["content_quality_score"],
            brand_safe=analysis["brand_safe"],
            has_sponsored_content=analysis["has_sponsored_content"],
            sponsored_brands=analysis["sponsored_brands"],
            language=analysis["language"],
            sentiment=analysis["sentiment"],
            analyzed_at=datetime.utcnow(),
            posts_analyzed=len(posts_data),
        )

    def _generate_mock_content_analysis(self, influencer: InfluencerBase, post_count: int) -> ContentAnalysis:
        """Generate realistic mock content analysis for testing."""
        import random

        niche = influencer.raw_data.get("discovery_niche", "lifestyle")
        try:
            niche_enum = Niche(niche)
        except ValueError:
            niche_enum = Niche.LIFESTYLE

        topics = self.topic_categories.get(niche_enum, self.topic_categories[Niche.LIFESTYLE])
        primary_topics = random.sample(topics, min(5, len(topics)))

        content_pillars = random.sample([
            "educational", "inspirational", "entertainment", "personal",
            "behind the scenes", "product reviews", "tutorials", "lifestyle"
        ], 3)

        has_sponsored = random.random() < 0.3
        sponsored_brands = []
        if has_sponsored:
            brand_pool = ["Nike", "Adidas", "Gymshark", "Sephora", "Glossier", "Fenty", "Apple", "Samsung", "Sony"]
            sponsored_brands = random.sample(brand_pool, random.randint(1, 3))

        return ContentAnalysis(
            primary_topics=primary_topics,
            content_pillars=content_pillars,
            posting_schedule=random.choice(["daily", "3x/week", "weekly", "irregular"]),
            content_quality_score=round(random.uniform(0.4, 0.9), 2),
            brand_safe=random.random() > 0.05,
            has_sponsored_content=has_sponsored,
            sponsored_brands=sponsored_brands,
            language="en",
            sentiment=random.choice(["positive", "neutral", "positive", "positive"]),  # Weighted positive
            analyzed_at=datetime.utcnow(),
            posts_analyzed=post_count,
        )

    async def _fetch_recent_posts(self, influencer: InfluencerBase, limit: int) -> List[Dict[str, Any]]:
        """Fetch recent posts from platform (override in subclasses)."""
        return []

    def _analyze_posts(self, posts: List[Dict[str, Any]], influencer: InfluencerBase) -> Dict[str, Any]:
        """Analyze a list of posts for content insights."""
        if not posts:
            return self._empty_analysis()

        all_captions = []
        all_hashtags = []
        sponsored_brands = set()
        has_sponsored = False
        post_times = []

        for post in posts:
            caption = post.get("caption", "") or post.get("text", "") or ""
            all_captions.append(caption)

            hashtags = re.findall(r"#(\w+)", caption.lower())
            all_hashtags.extend(hashtags)

            caption_lower = caption.lower()
            for keyword in self.sponsored_keywords:
                if keyword in caption_lower:
                    has_sponsored = True
                    brand_mentions = re.findall(r"@(\w+)", caption)
                    sponsored_brands.update(brand_mentions)
                    break

            if "timestamp" in post:
                post_times.append(post["timestamp"])
            elif "taken_at" in post:
                post_times.append(post["taken_at"])

        full_text = " ".join(all_captions)

        language = detect_language(full_text)

        sentiment = analyze_sentiment(full_text)

        primary_topics = self._extract_topics(full_text, all_hashtags)

        content_pillars = self._determine_content_pillars(full_text, primary_topics)

        posting_schedule = self._detect_posting_schedule(post_times)

        brand_safe = self._check_brand_safety(full_text)

        quality_score = self._calculate_quality_score(
            len(posts),
            influencer.follower_count,
            has_sponsored,
            brand_safe,
            posting_schedule != "irregular",
        )

        return {
            "primary_topics": primary_topics,
            "content_pillars": content_pillars,
            "posting_schedule": posting_schedule,
            "content_quality_score": quality_score,
            "brand_safe": brand_safe,
            "has_sponsored_content": has_sponsored,
            "sponsored_brands": list(sponsored_brands)[:10],
            "language": language,
            "sentiment": sentiment,
        }

    def _empty_analysis(self) -> Dict[str, Any]:
        """Return empty analysis structure."""
        return {
            "primary_topics": [],
            "content_pillars": [],
            "posting_schedule": "unknown",
            "content_quality_score": 0.0,
            "brand_safe": True,
            "has_sponsored_content": False,
            "sponsored_brands": [],
            "language": "en",
            "sentiment": "neutral",
        }

    def _extract_topics(self, text: str, hashtags: List[str]) -> List[str]:
        """Extract primary topics from text and hashtags."""
        text_lower = text.lower()
        topic_scores = {}

        for niche, keywords in self.topic_categories.items():
            score = 0
            for kw in keywords:
                if kw in text_lower:
                    score += 2  
            for tag in hashtags:
                if tag in [k.replace(" ", "") for k in keywords]:
                    score += 1
            if score > 0:
                topic_scores[niche.value] = score

        hashtag_counter = Counter(hashtags)
        for tag, count in hashtag_counter.most_common(10):
            if tag not in topic_scores:
                topic_scores[tag] = count * 0.5

        sorted_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, _ in sorted_topics[:8]]

    def _determine_content_pillars(self, text: str, topics: List[str]) -> List[str]:
        """Determine content pillars from text analysis."""
        pillars = []
        text_lower = text.lower()

        pillar_keywords = {
            "educational": ["how to", "tutorial", "guide", "tips", "learn", "explained", "lesson"],
            "inspirational": ["motivation", "inspire", "journey", "progress", "transformation", "mindset"],
            "entertainment": ["funny", "humor", "meme", "relatable", "lol", "haha", "entertaining"],
            "personal": ["my story", "personal", "life update", "behind the scenes", "daily life", "vlog"],
            "product reviews": ["review", "tested", "trying", "honest review", "worth it", "favorites"],
            "tutorials": ["step by step", "tutorial", "how i", "my routine", "process"],
            "lifestyle": ["routine", "day in the life", "morning routine", "evening routine", "lifestyle"],
            "behind the scenes": ["bts", "behind the scenes", "making of", "process", "workflow"],
        }

        for pillar, keywords in pillar_keywords.items():
            if any(kw in text_lower for kw in keywords):
                pillars.append(pillar)

        if not pillars:
            pillars = ["lifestyle", "personal"]

        return pillars[:4]

    def _detect_posting_schedule(self, post_times: List[Any]) -> str:
        """Detect posting schedule from post timestamps."""
        if len(post_times) < 3:
            return "insufficient data"

        parsed_times = []
        for t in post_times:
            if isinstance(t, (int, float)):
                parsed_times.append(datetime.fromtimestamp(t))
            elif isinstance(t, str):
                try:
                    parsed_times.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
                except:
                    pass
            elif isinstance(t, datetime):
                parsed_times.append(t)

        if len(parsed_times) < 3:
            return "irregular"

        parsed_times.sort()
        intervals = []
        for i in range(1, len(parsed_times)):
            delta = (parsed_times[i] - parsed_times[i-1]).total_seconds() / 3600  # hours
            intervals.append(delta)

        avg_interval = sum(intervals) / len(intervals)

        if avg_interval <= 24:
            return "daily"
        elif avg_interval <= 72:
            return "every 2-3 days"
        elif avg_interval <= 168:
            return "weekly"
        else:
            return "irregular"

    def _check_brand_safety(self, text: str) -> bool:
        """Check if content is brand-safe."""
        text_lower = text.lower()
        for keyword in self.unsafe_keywords:
            if keyword in text_lower:
                return False
        return True

    def _calculate_quality_score(
        self,
        posts_analyzed: int,
        follower_count: int,
        has_sponsored: bool,
        brand_safe: bool,
        consistent_posting: bool,
    ) -> float:
        """Calculate content quality score (0-1)."""
        from src.enrichment.base import calculate_content_quality_score

        if follower_count < 10000:
            est_engagement = 0.05
        elif follower_count < 50000:
            est_engagement = 0.03
        else:
            est_engagement = 0.02

        return calculate_content_quality_score(
            posts_analyzed=posts_analyzed,
            avg_engagement_rate=est_engagement,
            has_sponsored=has_sponsored,
            brand_safe=brand_safe,
            consistent_posting=consistent_posting,
        )

    async def enrich_contact(self, influencer: InfluencerBase):
        """Not implemented in content enricher."""
        raise NotImplementedError("Use ContactEnricher for contact extraction")

    async def enrich_cross_platform(self, influencer: InfluencerBase):
        """Not implemented in content enricher."""
        raise NotImplementedError("Use CrossPlatformEnricher for cross-platform analysis")


class InstagramContentEnricher(ContentEnricher):
    """Instagram-specific content enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.INSTAGRAM, **kwargs)

    async def _fetch_recent_posts(self, influencer: InfluencerBase, limit: int) -> List[Dict[str, Any]]:
        """Fetch recent Instagram posts."""
        posts = []

        try:
            if influencer.profile_url:
                response = await self._fetch(str(influencer.profile_url))
                soup = BeautifulSoup(response.text, "lxml")

                

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

                        user_data = data.get("entry_data", {}).get("ProfilePage", [{}])[0]
                        if not user_data:
                            user_data = data.get("props", {}).get("pageProps", {})

                        edges = user_data.get("graphql", {}).get("user", {}).get("edge_owner_to_timeline_media", {}).get("edges", [])

                        for edge in edges[:limit]:
                            node = edge.get("node", {})
                            caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                            caption = ""
                            if caption_edges:
                                caption = caption_edges[0].get("node", {}).get("text", "")

                            posts.append({
                                "caption": caption,
                                "timestamp": node.get("taken_at_timestamp"),
                                "likes": node.get("edge_liked_by", {}).get("count", 0),
                                "comments": node.get("edge_media_to_comment", {}).get("count", 0),
                                "is_video": node.get("is_video", False),
                                "shortcode": node.get("shortcode"),
                            })
                    except Exception as e:
                        logger.warning(f"Failed to parse Instagram posts: {e}")

        except Exception as e:
            logger.warning(f"Failed to fetch Instagram posts for @{influencer.username}: {e}")

        return posts


class YouTubeContentEnricher(ContentEnricher):
    """YouTube-specific content enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.YOUTUBE, **kwargs)

    async def _fetch_recent_posts(self, influencer: InfluencerBase, limit: int) -> List[Dict[str, Any]]:
        """Fetch recent YouTube videos."""
        return []


class TikTokContentEnricher(ContentEnricher):
    """TikTok-specific content enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.TIKTOK, **kwargs)

    async def _fetch_recent_posts(self, influencer: InfluencerBase, limit: int) -> List[Dict[str, Any]]:
        """Fetch recent TikTok videos."""
        return []


def get_content_enricher(platform: Platform, **kwargs) -> ContentEnricher:
    """Factory function to get platform-specific content enricher."""
    enrichers = {
        Platform.INSTAGRAM: InstagramContentEnricher,
        Platform.YOUTUBE: YouTubeContentEnricher,
        Platform.TIKTOK: TikTokContentEnricher,
    }
    enricher_class = enrichers.get(platform, ContentEnricher)
    return enricher_class(**kwargs)


__all__ = [
    "ContentEnricher",
    "InstagramContentEnricher",
    "YouTubeContentEnricher",
    "TikTokContentEnricher",
    "get_content_enricher",
]
