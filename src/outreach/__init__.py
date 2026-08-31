"""
Outreach module for Micro-Influencer Outreach System.
Provides AI-powered personalized outreach message generation and campaign management.
"""

from src.outreach.personalization import (
    PersonalizationEngine,
    PersonalizationPrompts,
)

from src.outreach.templates import (
    OutreachTemplateManager,
    InlineTemplateManager,
    get_template_manager,
)

from src.outreach.generator import (
    GenerationConfig,
    GenerationResult,
    OutreachGenerator,
    BatchOutreachGenerator,
    generate_outreach,
)

from src.outreach.campaign import (
    CampaignManager,
    CampaignBuilder,
    create_quick_campaign,
)

__all__ = [
    # Personalization
    "PersonalizationEngine",
    "PersonalizationPrompts",
    # Templates
    "OutreachTemplateManager",
    "InlineTemplateManager",
    "get_template_manager",
    # Generator
    "GenerationConfig",
    "GenerationResult",
    "OutreachGenerator",
    "BatchOutreachGenerator",
    "generate_outreach",
    # Campaign
    "CampaignManager",
    "CampaignBuilder",
    "create_quick_campaign",
]