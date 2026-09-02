from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, HttpUrl, EmailStr, computed_field
from uuid import uuid4


class Platform(str, Enum):
    """Supported social media platforms."""
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"


class Niche(str, Enum):
    """Supported influencer niches."""
    FITNESS = "fitness"
    FINTECH = "fintech"
    BEAUTY = "beauty"
    FASHION = "fashion"
    CRYPTO = "crypto"
    PARENTING = "parenting"
    GAMING = "gaming"
    LIFESTYLE = "lifestyle"
    TECHNOLOGY = "technology"


class InfluencerTier(str, Enum):
    """Influencer tier based on follower count."""
    NANO = "nano"
    MICRO = "micro"
    MID = "mid"
    MACRO = "macro"
    MEGA = "mega"


class OutreachType(str, Enum):
    """Types of outreach campaigns."""
    COLLABORATION = "collaboration_proposal"
    PRODUCT_SEEDING = "product_seeding"
    AFFILIATE = "affiliate_partnership"
    AMBASSADOR = "brand_ambassador"
    EVENT = "event_invitation"
    UGC = "ugc_request"


class InfluencerBase(BaseModel):
    """Base influencer data from discovery."""
    username: str = Field(..., description="Username/handle on the platform")
    platform: Platform = Field(..., description="Platform where influencer was found")
    profile_url: HttpUrl = Field(..., description="Direct URL to profile")
    display_name: Optional[str] = Field(None, description="Display name on profile")
    bio: Optional[str] = Field(None, description="Profile bio/description")
    follower_count: int = Field(..., ge=0, description="Number of followers")
    following_count: Optional[int] = Field(None, ge=0, description="Number of accounts followed")
    post_count: Optional[int] = Field(None, ge=0, description="Number of posts/videos")
    verified: bool = Field(False, description="Whether account is verified")
    profile_image_url: Optional[HttpUrl] = Field(None, description="Profile picture URL")
    external_url: Optional[HttpUrl] = Field(None, description="Link in bio / external website")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    discovery_method: str = Field(..., description="How this influencer was discovered")
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="Raw data from source")

    @computed_field
    @property
    def tier(self) -> InfluencerTier:
        """Determine influencer tier based on follower count."""
        if self.follower_count < 5000:
            return InfluencerTier.NANO
        elif self.follower_count < 100000:
            return InfluencerTier.MICRO
        elif self.follower_count < 500000:
            return InfluencerTier.MID
        elif self.follower_count < 1000000:
            return InfluencerTier.MACRO
        return InfluencerTier.MEGA

    @computed_field
    @property
    def is_micro_influencer(self) -> bool:
        """Check if influencer is in micro tier (5k-100k)."""
        return 5000 <= self.follower_count <= 100000


class EngagementMetrics(BaseModel):
    """Engagement metrics for an influencer."""
    avg_likes: float = Field(0.0, ge=0)
    avg_comments: float = Field(0.0, ge=0)
    avg_shares: float = Field(0.0, ge=0)
    avg_views: float = Field(0.0, ge=0)
    engagement_rate: float = Field(0.0, ge=0, le=1, description="Engagement rate as decimal (0.05 = 5%)")
    engagement_rate_percent: float = Field(0.0, ge=0, description="Engagement rate as percentage")
    post_frequency_per_week: float = Field(0.0, ge=0)
    recent_posts_analyzed: int = Field(0, ge=0)
    calculated_at: datetime = Field(default_factory=datetime.utcnow)


class ContactInfo(BaseModel):
    """Contact information extracted from profile."""
    email: Optional[EmailStr] = Field(None, description="Email address from bio or link in bio")
    emails_found: List[EmailStr] = Field(default_factory=list, description="All emails found")
    phone: Optional[str] = Field(None, description="Phone number if found")
    link_in_bio_url: Optional[HttpUrl] = Field(None, description="Link in bio URL (Linktree, etc.)")
    link_in_bio_platform: Optional[str] = Field(None, description="Platform: linktree, beacons, etc.")
    social_links: Dict[str, HttpUrl] = Field(default_factory=dict, description="Other social media links")
    business_inquiry_email: Optional[EmailStr] = Field(None, description="Dedicated business email")
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = Field(0.0, ge=0, le=1, description="Confidence in contact info accuracy")


class ContentAnalysis(BaseModel):
    """Content analysis results."""
    primary_topics: List[str] = Field(default_factory=list, description="Main content topics")
    content_pillars: List[str] = Field(default_factory=list, description="Content pillars/themes")
    posting_schedule: Optional[str] = Field(None, description="Detected posting schedule")
    content_quality_score: float = Field(0.0, ge=0, le=1, description="Content quality score")
    brand_safe: bool = Field(True, description="Whether content appears brand-safe")
    has_sponsored_content: bool = Field(False, description="Whether recent posts include sponsorships")
    sponsored_brands: List[str] = Field(default_factory=list, description="Brands mentioned in sponsored posts")
    language: str = Field("en", description="Primary language of content")
    sentiment: Literal["positive", "neutral", "negative"] = Field("neutral")
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    posts_analyzed: int = Field(0, ge=0)


class CrossPlatformPresence(BaseModel):
    """Cross-platform presence information."""
    platforms: Dict[Platform, Optional[str]] = Field(
        default_factory=dict,
        description="Platform -> username mapping"
    )
    total_followers: int = Field(0, ge=0)
    platform_count: int = Field(0, ge=0)
    consistent_branding: bool = Field(False)
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class EnrichedProfile(BaseModel):
    """Fully enriched influencer profile."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    influencer: InfluencerBase
    niche: Niche = Field(..., description="Classified niche")
    niche_confidence: float = Field(0.0, ge=0, le=1, description="Confidence in niche classification")

    engagement: EngagementMetrics = Field(default_factory=EngagementMetrics)
    contact: ContactInfo = Field(default_factory=ContactInfo)
    content: ContentAnalysis = Field(default_factory=ContentAnalysis)
    cross_platform: CrossPlatformPresence = Field(default_factory=CrossPlatformPresence)

    enrichment_version: str = Field("1.0")
    enriched_at: datetime = Field(default_factory=datetime.utcnow)
    enrichment_errors: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def overall_score(self) -> float:
        """Calculate overall suitability score (0-100)."""
        score = 0.0
        if self.influencer.is_micro_influencer:
            score += 30
        elif self.influencer.tier == InfluencerTier.NANO:
            score += 20
        elif self.influencer.tier == InfluencerTier.MID:
            score += 25
        else:
            score += 10

        score += min(self.engagement.engagement_rate * 100 * 3, 30)

        if self.contact.email:
            score += 15
        elif self.contact.emails_found:
            score += 10
        elif self.contact.link_in_bio_url:
            score += 5

        score += self.content.content_quality_score * 15

        score += min(self.cross_platform.platform_count * 2, 10)

        return min(score, 100.0)


class OutreachMessage(BaseModel):
    """Personalized outreach message."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    influencer_id: str = Field(..., description="Reference to enriched profile")
    template_type: OutreachType = Field(..., description="Template used")
    subject: str = Field(..., description="Email/DM subject line")
    body: str = Field(..., description="Message body")
    variant: int = Field(1, ge=1, le=5, description="Variant number (1-5)")
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    model_used: str = Field(..., description="LLM model used for generation")
    tokens_used: Optional[int] = Field(None, description="Tokens consumed")
    personalization_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Context used for personalization"
    )


class OutreachCampaign(BaseModel):
    """Collection of outreach messages for a campaign."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(..., description="Campaign name")
    brand_name: str = Field(..., description="Brand name")
    niche: Niche = Field(..., description="Target niche")
    messages: List[OutreachMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["draft", "review", "approved", "sent"] = Field("draft")

    @computed_field
    @property
    def total_messages(self) -> int:
        return len(self.messages)

    @computed_field
    @property
    def unique_influencers(self) -> int:
        return len(set(m.influencer_id for m in self.messages))


class DiscoveryResult(BaseModel):
    """Result of a discovery run."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    niche: Niche
    platform: Platform
    influencers_found: int = Field(0, ge=0)
    influencers: List[InfluencerBase] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    errors: List[str] = Field(default_factory=list)
    rate_limited: bool = False


class FilterResult(BaseModel):
    """Result of filtering and classification."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    input_count: int = Field(0, ge=0)
    passed_count: int = Field(0, ge=0)
    filtered_count: int = Field(0, ge=0)
    filtered_reasons: Dict[str, int] = Field(default_factory=dict)
    classified_niches: Dict[Niche, int] = Field(default_factory=dict)
    processed_at: datetime = Field(default_factory=datetime.utcnow)


class PipelineRun(BaseModel):
    """Complete pipeline run record."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    niches: List[Niche] = Field(default_factory=list)
    platforms: List[Platform] = Field(default_factory=list)
    target_count: int = Field(50, ge=1)

    discovery: Optional[DiscoveryResult] = None
    filter: Optional[FilterResult] = None
    enriched_profiles: List[EnrichedProfile] = Field(default_factory=list)
    outreach_campaigns: List[OutreachCampaign] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: Literal["running", "completed", "failed", "partial"] = "running"
    errors: List[str] = Field(default_factory=list)

    @computed_field
    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @computed_field
    @property
    def success_rate(self) -> float:
        if not self.enriched_profiles:
            return 0.0
        micro_count = sum(1 for p in self.enriched_profiles if p.influencer.is_micro_influencer)
        return micro_count / len(self.enriched_profiles) * 100


class DiscoverRequest(BaseModel):
    """Request for discovery operation."""
    niches: List[Niche] = Field(default_factory=list)
    platforms: List[Platform] = Field(default_factory=list)
    target_count: int = Field(50, ge=1, le=500)
    hashtags: Optional[List[str]] = Field(None)


class FilterRequest(BaseModel):
    """Request for filtering operation."""
    min_followers: int = Field(5000, ge=0)
    max_followers: int = Field(100000, ge=0)
    min_engagement_rate: float = Field(0.02, ge=0, le=1)
    require_contact: bool = False
    niches: Optional[List[Niche]] = None


class EnrichRequest(BaseModel):
    """Request for enrichment operation."""
    influencer_ids: Optional[List[str]] = None
    analyze_posts: int = Field(10, ge=1, le=50)
    check_cross_platform: bool = True
    extract_contacts: bool = True


class OutreachRequest(BaseModel):
    """Request for outreach generation."""
    influencer_ids: List[str]
    template_types: List[OutreachType] = Field(default_factory=list)
    variants_per_influencer: int = Field(3, ge=1, le=5)
    brand_name: str
    brand_description: str
    sender_name: str
    sender_email: EmailStr
    custom_context: Dict[str, Any] = Field(default_factory=dict)


class PipelineRequest(BaseModel):
    """Request for full pipeline run."""
    niches: List[Niche] = Field(default_factory=list)
    platforms: List[Platform] = Field(default_factory=list)
    target_count: int = Field(50, ge=1, le=500)
    filter_criteria: FilterRequest = Field(default_factory=FilterRequest)
    enrich_config: EnrichRequest = Field(default_factory=EnrichRequest)
    outreach_config: OutreachRequest = Field(default_factory=OutreachRequest)


__all__ = [
    "Platform",
    "Niche",
    "InfluencerTier",
    "OutreachType",
    "InfluencerBase",
    "EngagementMetrics",
    "ContactInfo",
    "ContentAnalysis",
    "CrossPlatformPresence",
    "EnrichedProfile",
    "OutreachMessage",
    "OutreachCampaign",
    "DiscoveryResult",
    "FilterResult",
    "PipelineRun",
    "DiscoverRequest",
    "FilterRequest",
    "EnrichRequest",
    "OutreachRequest",
    "PipelineRequest",
]
