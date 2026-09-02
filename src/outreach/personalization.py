import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from src.core.models import EnrichedProfile, Niche, Platform, OutreachType
from src.core.config import get_niche_keywords

logger = logging.getLogger(__name__)


class PersonalizationEngine:
    """
    Builds rich personalization context from EnrichedProfile for AI message generation.
    """

    def __init__(self):
        self.niche_keywords = get_niche_keywords()

    def build_context(
        self,
        profile: EnrichedProfile,
        brand_name: str,
        brand_description: str,
        campaign_type: OutreachType,
        sender_name: str,
        sender_title: str,
        sender_email: str,
        custom_context: Optional[Dict[str, Any]] = None,) -> Dict[str, Any]:
        """
        Build comprehensive personalization context for template rendering.

        Args:
            profile: Enriched influencer profile
            brand_name: Name of the brand
            brand_description: Description of the brand
            campaign_type: Type of outreach campaign
            sender_name: Sender's name
            sender_title: Sender's title
            sender_email: Sender's email
            custom_context: Additional custom context variables

        Returns:
            Dictionary with all personalization variables
        """
        influencer = profile.influencer

        context = {
            "brand_name": brand_name,
            "brand_description": brand_description,

            # Sender info
            "sender_name": sender_name,
            "sender_title": sender_title,
            "sender_email": sender_email,

            "influencer_name": influencer.display_name or influencer.username,
            "username": influencer.username,
            "platform": influencer.platform.value.title(),
            "platform_handle": f"@{influencer.username}",
            "profile_url": str(influencer.profile_url),
            "follower_count": self._format_count(influencer.follower_count),
            "follower_count_raw": influencer.follower_count,
            "bio": influencer.bio or "No bio available",

            "niche": profile.niche.value.title(),
            "niche_display": self.niche_keywords.get_niche_name(profile.niche),

            "engagement_rate": round(profile.engagement.engagement_rate_percent, 1),
            "engagement_rate_raw": profile.engagement.engagement_rate,
            "avg_likes": self._format_count(profile.engagement.avg_likes),
            "avg_comments": self._format_count(profile.engagement.avg_comments),

            "has_email": bool(profile.contact.email),
            "email": profile.contact.email or "not available",
            "link_in_bio": str(profile.contact.link_in_bio_url) if profile.contact.link_in_bio_url else "not available",

            "primary_topics": ", ".join(profile.content.primary_topics[:3]) if profile.content.primary_topics else "general content",
            "content_pillars": ", ".join(profile.content.content_pillars[:3]) if profile.content.content_pillars else "varied content",
            "content_quality": f"{profile.content.content_quality_score:.0%}",
            "brand_safe": "Yes" if profile.content.brand_safe else "No",
            "has_sponsored": "Yes" if profile.content.has_sponsored_content else "No",
            "sponsored_brands": ", ".join(profile.content.sponsored_brands[:3]) if profile.content.sponsored_brands else "None",
            "posting_schedule": profile.content.posting_schedule or "Regular",

            "platform_count": profile.cross_platform.platform_count,
            "total_followers": self._format_count(profile.cross_platform.total_followers),
            "consistent_branding": "Yes" if profile.cross_platform.consistent_branding else "No",

            "overall_score": round(profile.overall_score, 1),

            "current_date": datetime.utcnow().strftime("%B %d, %Y"),
            "current_year": datetime.utcnow().year,
        }

        context.update(self._build_recent_post_context(profile))

        context.update(self._build_niche_context(profile, campaign_type))

        context.update(self._build_campaign_context(profile, campaign_type))

        if custom_context:
            context.update(custom_context)

        return context

    def _build_recent_post_context(self, profile: EnrichedProfile) -> Dict[str, str]:
        """Build context from recent post analysis."""
        content = profile.content

        topics = content.primary_topics
        recent_topic = topics[0] if topics else "your latest content"
        recent_type = "post"

        if content.sentiment == "positive":
            personal_comment = "so inspiring and authentic"
        elif content.sentiment == "negative":
            personal_comment = "thought-provoking and real"
        else:
            personal_comment = "genuinely engaging"

        if content.has_sponsored_content and content.sponsored_brands:
            personal_comment = f"a great example of your work with {content.sponsored_brands[0]}"

        return {
            "recent_post_topic": recent_topic,
            "recent_post_type": recent_type,
            "personal_comment": personal_comment,
        }

    def _build_niche_context(self, profile: EnrichedProfile, campaign_type: OutreachType) -> Dict[str, str]:
        """Build niche-specific context."""
        niche = profile.niche
        influencer = profile.influencer

        alignment_reasons = {
            Niche.FITNESS: [
                "your authentic fitness journey and engaged community",
                "your expertise in workout routines and nutrition",
                "your genuine approach to health and wellness",
            ],
            Niche.FINTECH: [
                "your trusted financial insights and educated audience",
                "your ability to explain complex finance topics simply",
                "your audience's high intent for financial products",
            ],
            Niche.BEAUTY: [
                "your honest product reviews and beauty expertise",
                "your engaged community that trusts your recommendations",
                "your authentic approach to skincare and makeup",
            ],
            Niche.FASHION: [
                "your impeccable style and fashion authority",
                "your audience's strong purchase intent for fashion",
                "your authentic outfit inspiration content",
            ],
            Niche.CRYPTO: [
                "your deep crypto knowledge and community trust",
                "your audience's high engagement with Web3 topics",
                "your ability to simplify complex blockchain concepts",
            ],
            Niche.PARENTING: [
                "your relatable parenting content and community trust",
                "your authentic family lifestyle that resonates with parents",
                "your audience's high trust in your product recommendations",
            ],
            Niche.GAMING: [
                "your authentic gaming content and dedicated community",
                "your audience's high engagement with gaming products",
                "your expertise in gaming gear and setups",
            ],
            Niche.LIFESTYLE: [
                "your authentic lifestyle content and engaged following",
                "your relatable daily content that builds trust",
                "your versatile content that appeals to broad demographics",
            ],
            Niche.TECHNOLOGY: [
                "your technical expertise and developer audience",
                "your audience's high intent for tech tools and products",
                "your authentic coding and tech review content",
            ],
        }

        reasons = alignment_reasons.get(niche, alignment_reasons[Niche.LIFESTYLE])

        if profile.engagement.engagement_rate > 0.05:
            reason_idx = 0  
        elif profile.engagement.engagement_rate > 0.03:
            reason_idx = 1  
        else:
            reason_idx = 2  

        return {
            "alignment_reason": reasons[reason_idx],
        }

    def _build_campaign_context(self, profile: EnrichedProfile, campaign_type: OutreachType) -> Dict[str, str]:
        """Build campaign-type-specific context."""
        influencer = profile.influencer
        engagement_pct = round(profile.engagement.engagement_rate_percent, 1)
        follower_count = self._format_count(influencer.follower_count)

        campaign_contexts = {
            OutreachType.COLLABORATION: {
                "content_requirements": "3 feed posts + 5 stories over 4 weeks",
                "timeline": "4 weeks from agreement",
                "compensation": "$500-1000 + product",
            },
            OutreachType.PRODUCT_SEEDING: {
                "product_name": "our latest product",
                "product_value": "50",
                "product_description": "premium quality with natural ingredients",
                "key_features": "vegan, cruelty-free, sustainable packaging",
            },
            OutreachType.AFFILIATE: {
                "commission_rate": "20",
                "discount_code": f"{influencer.username.upper()}20",
                "discount_percent": "20",
            },
            OutreachType.AMBASSADOR: {
                "monthly_credit": "200",
                "posts_per_month": "4",
                "stories_per_month": "8",
                "brand_followers": "100K+",
            },
            OutreachType.EVENT: {
                "event_name": "Brand Launch Event",
                "event_date": "TBD",
                "event_location": "NYC / Virtual",
                "virtual_link": "zoom link provided",
                "event_highlights": "product demos, networking, content creation stations",
                "other_attendees": f"top {profile.niche.value} creators",
                "product_launch": "our new collection",
                "special_perks": "gift bag worth $200+",
                "travel_coverage": "travel + accommodation",
                "additional_perks": "exclusive product access",
                "rsvp_deadline": "this Friday",
            },
            OutreachType.UGC: {
                "campaign_name": "Summer Campaign",
                "video_count": "5",
                "video_length": "30-60 seconds",
                "photo_count": "10",
                "usage_rights": "paid social, website, email (12 months)",
                "budget_total": "1500",
                "budget_per_asset": "100",
                "creative_brief": "Show the product in your daily routine, highlight 2-3 key benefits, end with CTA",
            },
        }

        base_context = campaign_contexts.get(campaign_type, {})

        base_context.update({
            "engagement_rate": str(engagement_pct),
            "follower_count": follower_count,
            "niche": profile.niche.value,
        })

        return base_context

    def _format_count(self, count: Optional[float]) -> str:
        """Format count as human-readable string (e.g., 10.5K)."""
        if count is None:
            return "0"

        count = int(count)
        if count >= 1000000:
            return f"{count / 1000000:.1f}M"
        elif count >= 1000:
            return f"{count / 1000:.1f}K"
        return str(count)

    def extract_key_signals(self, profile: EnrichedProfile) -> Dict[str, Any]:
        """
        Extract key signals for AI prompt engineering.
        Returns structured data for LLM prompt construction.
        """
        return {
            "influencer": {
                "name": profile.influencer.display_name or profile.influencer.username,
                "username": profile.influencer.username,
                "platform": profile.influencer.platform.value,
                "tier": profile.influencer.tier.value,
                "follower_count": profile.influencer.follower_count,
                "verified": profile.influencer.verified,
            },
            "niche": {
                "primary": profile.niche.value,
                "confidence": profile.niche_confidence,
                "topics": profile.content.primary_topics,
                "pillars": profile.content.content_pillars,
            },
            "engagement": {
                "rate": profile.engagement.engagement_rate,
                "rate_percent": profile.engagement.engagement_rate_percent,
                "avg_likes": profile.engagement.avg_likes,
                "avg_comments": profile.engagement.avg_comments,
                "post_frequency": profile.engagement.post_frequency_per_week,
            },
            "content": {
                "quality_score": profile.content.content_quality_score,
                "brand_safe": profile.content.brand_safe,
                "has_sponsored": profile.content.has_sponsored_content,
                "sponsored_brands": profile.content.sponsored_brands,
                "sentiment": profile.content.sentiment,
                "language": profile.content.language,
                "posting_schedule": profile.content.posting_schedule,
            },
            "contact": {
                "has_email": bool(profile.contact.email),
                "email": profile.contact.email,
                "has_link_in_bio": bool(profile.contact.link_in_bio_url),
                "link_in_bio_platform": profile.contact.link_in_bio_platform,
                "social_links": list(profile.contact.social_links.keys()),
            },
            "cross_platform": {
                "platform_count": profile.cross_platform.platform_count,
                "platforms": {p.value: u for p, u in profile.cross_platform.platforms.items()},
                "total_followers": profile.cross_platform.total_followers,
                "consistent_branding": profile.cross_platform.consistent_branding,
            },
            "overall_score": profile.overall_score,
        }


class PersonalizationPrompts:
    """Pre-built prompts for different outreach types."""

    @staticmethod
    def get_system_prompt(campaign_type: OutreachType) -> str:
        """Get system prompt for campaign type."""
        base_prompt = """You are an expert outreach copywriter specializing in influencer marketing.
Write personalized, authentic outreach messages that feel human and build genuine connections.
Never use generic templates - always reference specific details about the influencer.
Keep messages concise, professional, and compelling."""

        type_prompts = {
            OutreachType.COLLABORATION: base_prompt + """
Focus on mutual value creation. Highlight specific alignment between brand and influencer.
Be clear about expectations, timeline, and compensation.""",
            OutreachType.PRODUCT_SEEDING: base_prompt + """
Focus on gifting with no strings attached. Emphasize product quality and genuine fit.
Make it clear there's no obligation to post.""",
            OutreachType.AFFILIATE: base_prompt + """
Focus on passive income opportunity. Highlight commission rates, cookie windows, and exclusivity.
Emphasize the win-win nature of affiliate partnerships.""",
            OutreachType.AMBASSADOR: base_prompt + """
Focus on long-term relationship building. Highlight exclusive perks, creative freedom, and growth.
Position as a partnership, not a transaction.""",
            OutreachType.EVENT: base_prompt + """
Focus on exclusive access and networking. Highlight unique experiences and content opportunities.
Create FOMO while being genuine about the value.""",
            OutreachType.UGC: base_prompt + """
Focus on creative collaboration. Be specific about deliverables, usage rights, and compensation.
Respect creative freedom while providing clear brief.""",
        }

        return type_prompts.get(campaign_type, base_prompt)

    @staticmethod
    def build_user_prompt(
        context: Dict[str, Any],
        template_type: OutreachType,
        variant: int = 1,
    ) -> str:
        """Build user prompt for message generation."""
        signals = context.get("_key_signals", {})

        prompt = f"""Generate a personalized {template_type.value.replace('_', ' ')} outreach message (variant {variant}).

INFLUENCER PROFILE:
- Name: {signals.get('influencer', {}).get('name', 'N/A')}
- Handle: @{signals.get('influencer', {}).get('username', 'N/A')}
- Platform: {signals.get('influencer', {}).get('platform', 'N/A')}
- Followers: {signals.get('influencer', {}).get('follower_count', 0):,}
- Tier: {signals.get('influencer', {}).get('tier', 'N/A')}
- Verified: {signals.get('influencer', {}).get('verified', False)}

NICHE & CONTENT:
- Primary Niche: {signals.get('niche', {}).get('primary', 'N/A')} (confidence: {signals.get('niche', {}).get('confidence', 0):.0%})
- Topics: {', '.join(signals.get('niche', {}).get('topics', [])[:3])}
- Content Pillars: {', '.join(signals.get('niche', {}).get('pillars', [])[:3])}

ENGAGEMENT:
- Rate: {signals.get('engagement', {}).get('rate_percent', 0):.1f}%
- Avg Likes: {signals.get('engagement', {}).get('avg_likes', 0):.0f}
- Avg Comments: {signals.get('engagement', {}).get('avg_comments', 0):.0f}
- Post Frequency: {signals.get('engagement', {}).get('post_frequency', 0):.1f}/week

CONTENT QUALITY:
- Quality Score: {signals.get('content', {}).get('quality_score', 0):.0%}
- Brand Safe: {signals.get('content', {}).get('brand_safe', True)}
- Has Sponsored Content: {signals.get('content', {}).get('has_sponsored', False)}
- Recent Sponsored Brands: {', '.join(signals.get('content', {}).get('sponsored_brands', [])[:3])}
- Sentiment: {signals.get('content', {}).get('sentiment', 'neutral')}
- Posting Schedule: {signals.get('content', {}).get('posting_schedule', 'regular')}

CONTACT:
- Has Email: {signals.get('contact', {}).get('has_email', False)}
- Link in Bio: {signals.get('contact', {}).get('has_link_in_bio', False)}
- Link in Bio Platform: {signals.get('contact', {}).get('link_in_bio_platform', 'N/A')}

CROSS-PLATFORM:
- Platform Count: {signals.get('cross_platform', {}).get('platform_count', 1)}
- Total Followers: {signals.get('cross_platform', {}).get('total_followers', 0):,}
- Consistent Branding: {signals.get('cross_platform', {}).get('consistent_branding', False)}

OVERALL SCORE: {signals.get('overall_score', 0):.1f}/100

BRAND: {context.get('brand_name', 'N/A')} - {context.get('brand_description', 'N/A')}
CAMPAIGN TYPE: {template_type.value}
SENDER: {context.get('sender_name', 'N/A')} ({context.get('sender_title', 'N/A')}) - {context.get('sender_email', 'N/A')}

REQUIREMENTS:
1. Write a compelling subject line (max 60 chars)
2. Write a personalized message body (150-400 words)
3. Reference specific details from the influencer's profile
4. Match the tone to the influencer's content style
5. Include clear call-to-action
6. Keep it professional but warm and human
7. Do NOT use placeholder brackets like {{variable}} - write actual values
8. Variant {variant}: {'More casual and friendly' if variant == 1 else 'More professional and direct' if variant == 2 else 'Short and punchy' if variant == 3 else 'Story-driven' if variant == 4 else 'Data-focused'}

Return ONLY the message in this format:
SUBJECT: [subject line]
BODY: [message body]"""

        return prompt


__all__ = [
    "PersonalizationEngine",
    "PersonalizationPrompts",
]
