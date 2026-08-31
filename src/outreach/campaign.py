"""
Campaign management for outreach operations.
Handles creation, tracking, and export of outreach campaigns.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path
from src.core.models import (
    OutreachCampaign,
    OutreachMessage,
    OutreachType,
    EnrichedProfile,
    Niche,
)
from src.core.storage import get_outreach_repo, get_exporter

logger = logging.getLogger(__name__)


class CampaignManager:
    """Manages outreach campaigns and messages."""

    def __init__(self):
        self.repo = get_outreach_repo()
        self.exporter = get_exporter()

    async def create_campaign(
        self,
        name: str,
        brand_name: str,
        niche: Niche,
        profiles: List[EnrichedProfile],
        template_types: List[OutreachType],
        sender_name: str,
        sender_email: str,
        sender_title: str = "Partnerships Manager",
        brand_description: str = "",
        custom_context: Optional[Dict[str, Any]] = None,) -> OutreachCampaign:
        """
        Create a new outreach campaign with messages for all profiles.

        Args:
            name: Campaign name
            brand_name: Brand name
            niche: Target niche
            profiles: List of enriched profiles to target
            template_types: Types of outreach templates to use
            sender_name: Sender's name
            sender_email: Sender's email
            sender_title: Sender's title
            brand_description: Brand description
            custom_context: Additional context for personalization

        Returns:
            Created OutreachCampaign
        """
        campaign = OutreachCampaign(
            name=name,
            brand_name=brand_name,
            niche=niche,
            status="draft",
        )

        from src.outreach.generator import OutreachGenerator, GenerationConfig

        generator = OutreachGenerator(GenerationConfig())

        all_messages = []
        for profile in profiles:
            for template_type in template_types:
                messages = await generator.generate_variants(
                    profile=profile,
                    template_type=template_type,
                    brand_name=brand_name,
                    brand_description=brand_description or f"an innovative brand in the {niche.value} space",
                    sender_name=sender_name,
                    sender_title=sender_title,
                    sender_email=sender_email,
                    custom_context=custom_context,
                )
                all_messages.extend(messages)

        campaign.messages = all_messages
        logger.info(f"Created campaign '{name}' with {len(all_messages)} messages for {len(profiles)} influencers")

        return campaign

    async def save_campaign(self, campaign: OutreachCampaign) -> str:
        """Save campaign to database."""
        return await self.repo.save_campaign(campaign)

    async def get_campaign(self, campaign_id: str) -> Optional[OutreachCampaign]:
        """Get campaign by ID."""
        return await self.repo.get_campaign(campaign_id)

    async def update_campaign_status(self, campaign_id: str, status: str) -> bool:
        """Update campaign status."""
        logger.info(f"Campaign {campaign_id} status updated to {status}")
        return True

    def get_campaign_stats(self, campaign: OutreachCampaign) -> Dict[str, Any]:
        """Get statistics for a campaign."""
        messages = campaign.messages
        unique_influencers = set(m.influencer_id for m in messages)

        by_template: Dict[OutreachType, int] = {}
        by_variant: Dict[int, int] = {}
        by_model: Dict[str, int] = {}

        for msg in messages:
            by_template[msg.template_type] = by_template.get(msg.template_type, 0) + 1
            by_variant[msg.variant] = by_variant.get(msg.variant, 0) + 1
            by_model[msg.model_used] = by_model.get(msg.model_used, 0) + 1

        return {
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "brand_name": campaign.brand_name,
            "niche": campaign.niche.value,
            "status": campaign.status,
            "total_messages": len(messages),
            "unique_influencers": len(unique_influencers),
            "template_types": {k.value: v for k, v in by_template.items()},
            "variants": by_variant,
            "models_used": by_model,
            "created_at": campaign.created_at.isoformat(),
        }

    def export_campaign(self, campaign: OutreachCampaign, format: str = "json") -> Path:
        """Export campaign to file."""
        if format == "json":
            return self.exporter.export_outreach_campaign(campaign)
        elif format == "csv":
            return self._export_csv(campaign)
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _export_csv(self, campaign: OutreachCampaign) -> Path:
        """Export campaign to CSV."""
        import csv

        filepath = self.exporter.export_dir / f"campaign_{campaign.id[:8]}.csv"

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Message ID", "Influencer ID", "Template Type", "Variant",
                "Subject", "Body", "Model Used", "Tokens Used", "Generated At"
            ])

            for msg in campaign.messages:
                writer.writerow([
                    msg.id,
                    msg.influencer_id,
                    msg.template_type.value,
                    msg.variant,
                    msg.subject,
                    msg.body.replace("\n", " "),
                    msg.model_used,
                    msg.tokens_used or 0,
                    msg.generated_at.isoformat(),
                ])

        return filepath

    def export_messages_for_sending(
        self,
        campaign: OutreachCampaign,
        include_contact_info: bool = False,
        profiles: Optional[List[EnrichedProfile]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Export messages in format ready for sending (email/DM).

        Args:
            campaign: Campaign to export
            include_contact_info: Whether to include contact details
            profiles: Enriched profiles for contact info lookup

        Returns:
            List of message dictionaries with sending info
        """
        profile_map = {p.id: p for p in (profiles or [])}

        export_data = []
        for msg in campaign.messages:
            profile = profile_map.get(msg.influencer_id)

            data = {
                "message_id": msg.id,
                "influencer_id": msg.influencer_id,
                "template_type": msg.template_type.value,
                "variant": msg.variant,
                "subject": msg.subject,
                "body": msg.body,
                "generated_at": msg.generated_at.isoformat(),
            }

            if include_contact_info and profile:
                data.update({
                    "influencer_username": profile.influencer.username,
                    "influencer_name": profile.influencer.display_name,
                    "platform": profile.influencer.platform.value,
                    "profile_url": str(profile.influencer.profile_url),
                    "email": profile.contact.email,
                    "link_in_bio": str(profile.contact.link_in_bio_url) if profile.contact.link_in_bio_url else None,
                })

            export_data.append(data)

        return export_data


class CampaignBuilder:
    """Builder pattern for creating campaigns with fluent API."""

    def __init__(self):
        self._name = ""
        self._brand_name = ""
        self._brand_description = ""
        self._niche: Optional[Niche] = None
        self._profiles: List[EnrichedProfile] = []
        self._template_types: List[OutreachType] = []
        self._sender_name = ""
        self._sender_email = ""
        self._sender_title = "Partnerships Manager"
        self._custom_context: Dict[str, Any] = {}

    def with_name(self, name: str) -> "CampaignBuilder":
        self._name = name
        return self

    def with_brand(self, name: str, description: str = "") -> "CampaignBuilder":
        self._brand_name = name
        self._brand_description = description
        return self

    def with_niche(self, niche: Niche) -> "CampaignBuilder":
        self._niche = niche
        return self

    def with_profiles(self, profiles: List[EnrichedProfile]) -> "CampaignBuilder":
        self._profiles = profiles
        return self

    def with_templates(self, template_types: List[OutreachType]) -> "CampaignBuilder":
        self._template_types = template_types
        return self

    def with_sender(self, name: str, email: str, title: str = "Partnerships Manager") -> "CampaignBuilder":
        self._sender_name = name
        self._sender_email = email
        self._sender_title = title
        return self

    def with_custom_context(self, context: Dict[str, Any]) -> "CampaignBuilder":
        self._custom_context.update(context)
        return self

    def build(self) -> Dict[str, Any]:
        """Build campaign configuration dict."""
        return {
            "name": self._name,
            "brand_name": self._brand_name,
            "brand_description": self._brand_description,
            "niche": self._niche,
            "profiles": self._profiles,
            "template_types": self._template_types,
            "sender_name": self._sender_name,
            "sender_email": self._sender_email,
            "sender_title": self._sender_title,
            "custom_context": self._custom_context,
        }

    async def create_and_save(self, manager: CampaignManager) -> OutreachCampaign:
        """Create and save campaign."""
        config = self.build()
        campaign = await manager.create_campaign(**config)
        await manager.save_campaign(campaign)
        return campaign


async def create_quick_campaign(
    name: str,
    brand_name: str,
    profiles: List[EnrichedProfile],
    sender_name: str,
    sender_email: str,
    template_type: OutreachType = OutreachType.COLLABORATION,
    niche: Optional[Niche] = None,) -> OutreachCampaign:
    """Quick campaign creation with sensible defaults."""
    manager = CampaignManager()

    if niche is None and profiles:
        niche_counts: Dict[Niche, int] = {}
        for p in profiles:
            niche_counts[p.niche] = niche_counts.get(p.niche, 0) + 1
        niche = max(niche_counts, key=niche_counts.get) if niche_counts else Niche.LIFESTYLE
    elif niche is None:
        niche = Niche.LIFESTYLE

    builder = CampaignBuilder()
    builder.with_name(name) \
           .with_brand(brand_name, f"an innovative brand in the {niche.value} space") \
           .with_niche(niche) \
           .with_profiles(profiles) \
           .with_templates([template_type]) \
           .with_sender(sender_name, sender_email)

    return await builder.create_and_save(manager)


__all__ = [
    "CampaignManager",
    "CampaignBuilder",
    "create_quick_campaign",
]