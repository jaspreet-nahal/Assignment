import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from jinja2 import Environment, FileSystemLoader, select_autoescape, Template
from src.core.config import get_outreach_templates
from src.core.models import OutreachType
logger = logging.getLogger(__name__)


class OutreachTemplateManager:
    """Manages outreach templates with Jinja2 rendering."""

    def __init__(self, template_dir: Optional[Path] = None):
        self.template_dir = template_dir or (
            Path(__file__).parent.parent.parent / "config" / "templates"
        )
        self.templates_config = get_outreach_templates()

        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        self.env.filters["format_count"] = self._format_count_filter
        self.env.filters["title_case"] = lambda x: x.title() if x else ""
        self.env.filters["upper"] = lambda x: x.upper() if x else ""
        self.env.filters["lower"] = lambda x: x.lower() if x else ""

        self._compiled_templates: Dict[OutreachType, Template] = {}

    def _format_count_filter(self, count: Any) -> str:
        """Jinja2 filter to format counts as K/M."""
        if count is None:
            return "0"
        try:
            count = int(count)
        except (ValueError, TypeError):
            return str(count)

        if count >= 1000000:
            return f"{count / 1000000:.1f}M"
        elif count >= 1000:
            return f"{count / 1000:.1f}K"
        return str(count)

    def get_template(self, template_type: OutreachType) -> Optional[Template]:
        """Get compiled template for outreach type."""
        if template_type in self._compiled_templates:
            return self._compiled_templates[template_type]

        template_config = self.templates_config.get_template(template_type)
        if not template_config:
            logger.warning(f"No template found for {template_type.value}")
            return None

        template_str = template_config.get("body", "")
        subject_str = template_config.get("subject", "")

        full_template = f"SUBJECT: {subject_str}\n\nBODY: {template_str}"

        try:
            template = self.env.from_string(full_template)
            self._compiled_templates[template_type] = template
            return template
        except Exception as e:
            logger.error(f"Failed to compile template for {template_type.value}: {e}")
            return None

    def render(
        self,
        template_type: OutreachType,
        context: Dict[str, Any],) -> Optional[Dict[str, str]]:
        """
        Render template with context.

        Returns:
            Dict with 'subject' and 'body' keys, or None if failed
        """
        template = self.get_template(template_type)
        if not template:
            return None

        try:
            rendered = template.render( context)

            subject = ""
            body = ""

            lines = rendered.split("\n")
            in_body = False
            body_lines = []

            for line in lines:
                if line.startswith("SUBJECT:"):
                    subject = line[8:].strip()
                elif line.startswith("BODY:"):
                    in_body = True
                    body_lines.append(line[5:].strip())
                elif in_body:
                    body_lines.append(line)

            body = "\n".join(body_lines).strip()

            return {
                "subject": subject,
                "body": body,
            }

        except Exception as e:
            logger.error(f"Failed to render template {template_type.value}: {e}")
            return None

    def render_multiple(
        self,
        template_type: OutreachType,
        contexts: List[Dict[str, Any]],) -> List[Optional[Dict[str, str]]]:
        """Render template for multiple contexts."""
        return [self.render(template_type, ctx) for ctx in contexts]

    def get_defaults(self) -> Dict[str, Any]:
        """Get default template values."""
        return self.templates_config.get_defaults()

    def get_all_template_types(self) -> List[OutreachType]:
        """Get all available template types."""
        names = self.templates_config.get_template_names()
        return [OutreachType(name) for name in names if name in OutreachType.__members__]

    def validate_template(self, template_type: OutreachType) -> Dict[str, Any]:
        """Validate template by rendering with sample data."""
        sample_context = self._get_sample_context(template_type)
        result = self.render(template_type, sample_context)

        return {
            "valid": result is not None,
            "subject": result.get("subject", "") if result else "",
            "body_preview": result.get("body", "")[:200] if result else "",
            "error": None if result else "Template rendering failed",
        }

    def _get_sample_context(self, template_type: OutreachType) -> Dict[str, Any]:
        """Get sample context for template validation."""
        defaults = self.get_defaults()

        return {
            "brand_name": "SampleBrand",
            "brand_description": "an innovative brand in the lifestyle space",
            "sender_name": "Alex Johnson",
            "sender_title": "Partnerships Manager",
            "sender_email": "alex@samplebrand.com",
            "influencer_name": "Sarah Johnson",
            "username": "sarahj_fitness",
            "platform": "Instagram",
            "platform_handle": "@sarahj_fitness",
            "profile_url": "https://instagram.com/sarahj_fitness",
            "follower_count": "25.5K",
            "follower_count_raw": 25500,
            "bio": "Fitness coach | Nutrition | Mom of 2 | DM for collabs",
            "niche": "Fitness",
            "niche_display": "Fitness & Wellness",
            "engagement_rate": "4.2",
            "engagement_rate_raw": 0.042,
            "avg_likes": "1.1K",
            "avg_comments": "85",
            "has_email": True,
            "email": "sarah@fitnesscoach.com",
            "link_in_bio": "https://linktr.ee/sarahj_fitness",
            "primary_topics": "workout, nutrition, fitness motivation",
            "content_pillars": "educational, inspirational, personal",
            "content_quality": "85%",
            "brand_safe": "Yes",
            "has_sponsored": "Yes",
            "sponsored_brands": "Nike, Gymshark",
            "posting_schedule": "daily",
            "platform_count": 3,
            "total_followers": "45K",
            "consistent_branding": "Yes",
            "overall_score": "82.5",
            "current_date": "January 15, 2025",
            "current_year": 2025,
            "alignment_reason": "your authentic fitness journey and engaged community",
            **defaults,
        }

    def preview_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """Preview all templates with sample data."""
        previews = {}
        for template_type in self.get_all_template_types():
            previews[template_type.value] = self.validate_template(template_type)
        return previews


class InlineTemplateManager:
    """Alternative: Inline templates defined in code (no file dependency)."""

    INLINE_TEMPLATES = {
        OutreachType.COLLABORATION: {
            "subject": "Collaboration Opportunity with {{ brand_name }} for {{ influencer_name }}",
            "body": """Hi {{ influencer_name }},

I've been following your content on {{ platform }} and absolutely love your {{ niche }} content! Your post about {{ recent_post_topic }} really resonated with me - {{ personal_comment }}.

I'm reaching out from {{ brand_name }}, a {{ brand_description }}. We think you'd be a perfect fit for our upcoming campaign because {{ alignment_reason }}.

 What we're looking for: 
- {{ content_requirements }}
- Timeline: {{ timeline }}
- Compensation: {{ compensation }}

 Why you're a great fit: 
- Your {{ engagement_rate }}% engagement rate shows genuine audience connection
- Your audience aligns perfectly with our target demographic
- Your authentic voice matches our brand values

Would you be open to a quick call to discuss this further? I'd love to share more details and hear your thoughts.

Best regards,
{{ sender_name }}
{{ sender_title }}
{{ brand_name }}
{{ sender_email }}""",
        },
        OutreachType.PRODUCT_SEEDING: {
            "subject": "Gift for you from {{ brand_name }} 🎁",
            "body": """Hi {{ influencer_name }},

Love your {{ niche }} content! Your recent {{ recent_post_type }} about {{ recent_post_topic }} was {{ personal_comment }}.

I'm {{ sender_name }} from {{ brand_name }} - we {{ brand_description }}. We'd love to send you our {{ product_name }} (worth ${{ product_value }}) to try out - no strings attached!

 What's included: 
- {{ product_description }}
- {{ key_features }}

If you genuinely love it and want to share with your audience, that would be amazing - but absolutely no pressure either way. We just think you'd genuinely enjoy it.

Interested? Just reply with your best shipping address and I'll get it sent out this week.

Cheers,
{{ sender_name }}
{{ brand_name }}""",
        },
        OutreachType.AFFILIATE: {
            "subject": "Affiliate Partnership: Earn {{ commission_rate }}% with {{ brand_name }}",
            "body": """Hi {{ influencer_name }},

I've been impressed by your {{ niche }} content on {{ platform }} - especially your take on {{ recent_post_topic }}. Your audience clearly trusts your recommendations.

I'm {{ sender_name }} from {{ brand_name }}, where we {{ brand_description }}. We're launching an affiliate program and would love to have you as a founding partner.

 Program highlights: 
- {{ commission_rate }}% commission on all sales
- 30-day cookie window
- Exclusive {{ discount_code }} for your followers ({{ discount_percent }}% off)
- Monthly payouts via PayPal/bank transfer
- Dedicated affiliate dashboard with real-time tracking
- Early access to new products

 Why this works for you: 
- Your {{ follower_count }} followers in the {{ niche }} niche
- {{ engagement_rate }}% engagement shows high purchase intent
- Passive income stream alongside your content

Ready to join? I'll set up your custom tracking link and dashboard today.

Best,
{{ sender_name }}
{{ brand_name }}
{{ sender_email }}""",
        },
        OutreachType.AMBASSADOR: {
            "subject": "Brand Ambassador Opportunity with {{ brand_name }}",
            "body": """Hi {{ influencer_name }},

Your {{ niche }} content on {{ platform }} has caught our attention! Your post about {{ recent_post_topic }} showed exactly the kind of authentic engagement we value.

I'm {{ sender_name }} from {{ brand_name }} - {{ brand_description }}. We're looking for long-term brand ambassadors and you're at the top of our list.

 Ambassador perks: 
- Monthly product credits (${{ monthly_credit }}/month)
- Exclusive access to new launches
- {{ commission_rate }}% affiliate commission on all sales
- Featured on our brand channels ({{ brand_followers }} followers)
- Invitation to brand events & trips
- Direct line to our product team for feedback

 Commitment: 
- {{ posts_per_month }} posts/month + {{ stories_per_month }} stories/month
- 6-month initial term
- Creative freedom - we trust your voice!

Your {{ follower_count }} followers and {{ engagement_rate }}% engagement make you an ideal partner. Interested in learning more?

Let's chat this week -
{{ sender_name }}
{{ brand_name }}""",
        },
        OutreachType.EVENT: {
            "subject": "Exclusive Invite: {{ event_name }} - {{ event_date }}",
            "body": """Hi {{ influencer_name }},

Big fan of your {{ niche }} content! Your perspective on {{ recent_post_topic }} is exactly why we'd love to have you at our upcoming event.

I'm {{ sender_name }} from {{ brand_name }}. We're hosting  {{ event_name }}  on  {{ event_date }}  at  {{ event_location }}  (or virtual: {{ virtual_link }}).

 What's happening: 
- {{ event_highlights }}
- Network with {{ other_attendees }}
- First look at {{ product_launch }}
- Content creation opportunities
- {{ special_perks }}

We'd cover your {{ travel_coverage }} and provide {{ additional_perks }}. This would be a great chance to create content for your {{ platform }} audience while connecting with other {{ niche }} creators.

Can you make it? Let me know by {{ rsvp_deadline }} and I'll send the details.

Excited about the possibility!
{{ sender_name }}
{{ brand_name }}""",
        },
        OutreachType.UGC: {
            "subject": "Paid UGC Opportunity: {{ brand_name }} x {{ influencer_name }}",
            "body": """Hi {{ influencer_name }},

Love your content style on {{ platform }}! Your {{ recent_post_type }} about {{ recent_post_topic }} has that authentic feel we're looking for.

I'm {{ sender_name }} from {{ brand_name }}. We're looking for creators to produce UGC (User Generated Content) for our {{ campaign_name }} campaign.

 Project details: 
- {{ video_count }} videos ({{ video_length }} each)
- {{ photo_count }} photos
- Usage rights: {{ usage_rights }}
- Timeline: {{ timeline }}
- Budget: ${{ budget_total }} total (${{ budget_per_asset }}/asset)

 Creative brief: 
{{ creative_brief }}

 Why you: 
- Your {{ engagement_rate }}% engagement rate
- Authentic {{ niche }} content style
- Professional quality with relatable delivery

If interested, I'll send the full brief and contract. We move fast - first shoot could be next week!

Best,
{{ sender_name }}
{{ brand_name }}
{{ sender_email }}""",
        },
    }

    @classmethod
    def render(cls, template_type: OutreachType, context: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Render inline template."""
        template_data = cls.INLINE_TEMPLATES.get(template_type)
        if not template_data:
            return None

        try:
            env = Environment(autoescape=select_autoescape())
            subject_template = env.from_string(template_data["subject"])
            body_template = env.from_string(template_data["body"])

            subject = subject_template.render( context)
            body = body_template.render( context)

            return {"subject": subject.strip(), "body": body.strip()}
        except Exception as e:
            logger.error(f"Failed to render inline template {template_type.value}: {e}")
            return None


_template_manager: Optional[OutreachTemplateManager] = None


def get_template_manager() -> OutreachTemplateManager:
    """Get global template manager instance."""
    global _template_manager
    if _template_manager is None:
        _template_manager = OutreachTemplateManager()
    return _template_manager


__all__ = [
    "OutreachTemplateManager",
    "InlineTemplateManager",
    "get_template_manager",
]
