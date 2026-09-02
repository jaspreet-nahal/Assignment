import asyncio
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Any
import google.generativeai as genai
from src.core.config import get_settings
from src.core.models import (
    EnrichedProfile,
    OutreachMessage,
    OutreachType,
    OutreachCampaign,
    Niche,
)
from src.outreach.personalization import PersonalizationEngine, PersonalizationPrompts
from src.outreach.templates import get_template_manager, InlineTemplateManager

logger = logging.getLogger(__name__)


@dataclass
class GenerationConfig:
    """Configuration for outreach generation."""
    model_name: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 500
    variants_per_influencer: int = 3
    use_ai: bool = True
    fallback_to_templates: bool = True


@dataclass
class GenerationResult:
    """Result of outreach generation."""
    messages: List[OutreachMessage]
    successful: int
    failed: int
    errors: List[str]
    tokens_used: int
    duration_seconds: float


class OutreachGenerator:
    """
    Generates personalized outreach messages using AI (Gemini) with template fallback.
    """

    def __init__(self, config: Optional[GenerationConfig] = None, api_key: Optional[str] = None):
        self.config = config or GenerationConfig(
            model_name=get_settings().outreach.gemini_model,
            temperature=get_settings().outreach.temperature,
            max_tokens=get_settings().outreach.max_tokens,
            variants_per_influencer=get_settings().outreach.variants_per_influencer,
        )

        self.api_key = api_key or get_settings().gemini_api_key or os.getenv("GEMINI_API_KEY")
        self.personalization = PersonalizationEngine()
        self.template_manager = get_template_manager()

        self.model = None
        if self.api_key and self.config.use_ai:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel(self.config.model_name)
                logger.info(f"Initialized Gemini model: {self.config.model_name}")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini: {e}. Will use template fallback.")
                self.model = None

    async def generate_for_campaign(
        self,
        profiles: List[EnrichedProfile],
        campaign: OutreachCampaign,
        template_types: Optional[List[OutreachType]] = None,) -> List[OutreachMessage]:
        """
        Generate outreach messages for a campaign.

        Args:
            profiles: List of enriched influencer profiles
            campaign: Campaign configuration
            template_types: Specific template types to use (defaults to campaign's or all)

        Returns:
            List of generated OutreachMessage objects
        """
        if template_types is None:
            template_types = [OutreachType.COLLABORATION]  # Default

        all_messages = []
        semaphore = asyncio.Semaphore(5)  
        async def generate_for_profile(profile: EnrichedProfile) -> List[OutreachMessage]:
            async with semaphore:
                messages = []
                for template_type in template_types:
                    try:
                        variants = await self.generate_variants(
                            profile=profile,
                            template_type=template_type,
                            brand_name=campaign.brand_name,
                            brand_description="", 
                            sender_name="Partnerships Team",
                            sender_title="Partnerships Manager",
                            sender_email="partnerships@brand.com",
                        )
                        for variant in variants:
                            variant.influencer_id = profile.id
                            messages.append(variant)
                    except Exception as e:
                        logger.error(f"Failed to generate {template_type.value} for {profile.influencer.username}: {e}")

                return messages

        tasks = [generate_for_profile(p) for p in profiles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Profile generation failed: {result}")
            elif isinstance(result, list):
                all_messages.extend(result)

        return all_messages

    async def generate_variants(
        self,
        profile: EnrichedProfile,
        template_type: OutreachType,
        brand_name: str,
        brand_description: str,
        sender_name: str,
        sender_title: str,
        sender_email: str,
        custom_context: Optional[Dict[str, Any]] = None,) -> List[OutreachMessage]:
        """
        Generate multiple variants of an outreach message.

        Args:
            profile: Enriched influencer profile
            template_type: Type of outreach template
            brand_name: Brand name
            brand_description: Brand description
            sender_name: Sender's name
            sender_title: Sender's title
            sender_email: Sender's email
            custom_context: Additional context variables

        Returns:
            List of OutreachMessage objects (one per variant)
        """
        context = self.personalization.build_context(
            profile=profile,
            brand_name=brand_name,
            brand_description=brand_description,
            campaign_type=template_type,
            sender_name=sender_name,
            sender_title=sender_title,
            sender_email=sender_email,
            custom_context=custom_context,
        )

        context["_key_signals"] = self.personalization.extract_key_signals(profile)

        messages = []

        if self.model and self.config.use_ai:
            try:
                ai_messages = await self._generate_with_ai(
                    profile=profile,
                    template_type=template_type,
                    context=context,
                )
                messages.extend(ai_messages)
            except Exception as e:
                logger.warning(f"AI generation failed, falling back to templates: {e}")

        while len(messages) < self.config.variants_per_influencer:
            variant_num = len(messages) + 1
            template_msg = self._generate_with_template(
                profile=profile,
                template_type=template_type,
                context=context,
                variant=variant_num,
            )
            if template_msg:
                messages.append(template_msg)
            else:
                break

        return messages[:self.config.variants_per_influencer]

    async def _generate_with_ai(
        self,
        profile: EnrichedProfile,
        template_type: OutreachType,
        context: Dict[str, Any],) -> List[OutreachMessage]:
        """Generate messages using Gemini AI."""
        messages = []

        system_prompt = PersonalizationPrompts.get_system_prompt(template_type)

        for variant in range(1, self.config.variants_per_influencer + 1):
            user_prompt = PersonalizationPrompts.build_user_prompt(
                context=context,
                template_type=template_type,
                variant=variant,
            )

            try:
                full_prompt = f"{system_prompt}\n\n{user_prompt}"

                generation_config = genai.types.GenerationConfig(
                    temperature=self.config.temperature,
                    max_output_tokens=self.config.max_tokens,
                )

                response = await asyncio.to_thread(
                    self.model.generate_content,
                    full_prompt,
                    generation_config=generation_config,
                )

                if response and response.text:
                    subject, body = self._parse_ai_response(response.text)

                    if subject and body:
                        messages.append(OutreachMessage(
                            influencer_id=profile.id,
                            template_type=template_type,
                            subject=subject,
                            body=body,
                            variant=variant,
                            model_used=self.config.model_name,
                            tokens_used=self._estimate_tokens(full_prompt, response.text),
                            personalization_context={
                                "key_signals": context.get("_key_signals", {}),
                                "variant": variant,
                            },
                        ))

            except Exception as e:
                logger.warning(f"AI variant {variant} failed: {e}")

        return messages

    def _generate_with_template(
        self,
        profile: EnrichedProfile,
        template_type: OutreachType,
        context: Dict[str, Any],
        variant: int,) -> Optional[OutreachMessage]:
        """Generate message using Jinja2 templates."""
        result = InlineTemplateManager.render(template_type, context)

        if not result:
            result = self.template_manager.render(template_type, context)

        if not result:
            return None

        return OutreachMessage(
            influencer_id=profile.id,
            template_type=template_type,
            subject=result["subject"],
            body=result["body"],
            variant=variant,
            model_used="template",
            tokens_used=0,
            personalization_context={
                "key_signals": context.get("_key_signals", {}),
                "variant": variant,
            },
        )

    def _parse_ai_response(self, text: str) -> tuple[Optional[str], Optional[str]]:
        """Parse AI response into subject and body."""
        subject = None
        body = None

        lines = text.strip().split("\n")
        body_lines = []
        in_body = False

        for line in lines:
            line_stripped = line.strip()
            if line_stripped.upper().startswith("SUBJECT:"):
                subject = line_stripped[8:].strip()
            elif line_stripped.upper().startswith("BODY:"):
                in_body = True
                body_lines.append(line_stripped[5:].strip())
            elif in_body:
                body_lines.append(line)

        if body_lines:
            body = "\n".join(body_lines).strip()

        if not subject and not body and lines:
            subject = lines[0].strip()
            body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        return subject, body

    def _estimate_tokens(self, prompt: str, response: str) -> int:
        """Rough token estimation."""
        return (len(prompt) + len(response)) // 4

    async def generate_single(
        self,
        profile: EnrichedProfile,
        template_type: OutreachType,
        brand_name: str,
        brand_description: str,
        sender_name: str,
        sender_title: str,
        sender_email: str,
        variant: int = 1,) -> Optional[OutreachMessage]:
        """Generate a single outreach message variant."""
        messages = await self.generate_variants(
            profile=profile,
            template_type=template_type,
            brand_name=brand_name,
            brand_description=brand_description,
            sender_name=sender_name,
            sender_title=sender_title,
            sender_email=sender_email,
        )

        if messages and variant <= len(messages):
            return messages[variant - 1]
        elif messages:
            return messages[0]

        return None

    def get_available_models(self) -> List[str]:
        """Get list of available Gemini models."""
        if not self.api_key:
            return []
        try:
            models = genai.list_models()
            return [m.name for m in models if "generateContent" in m.supported_generation_methods]
        except Exception:
            return []


class BatchOutreachGenerator:
    """Generates outreach for large batches of influencers."""

    def __init__(self, generator: OutreachGenerator, batch_size: int = 20):
        self.generator = generator
        self.batch_size = batch_size

    async def generate_for_profiles(
        self,
        profiles: List[EnrichedProfile],
        brand_name: str,
        brand_description: str,
        sender_name: str,
        sender_title: str,
        sender_email: str,
        template_types: List[OutreachType],
        custom_context: Optional[Dict[str, Any]] = None,) -> List[OutreachMessage]:
        """Generate outreach for multiple profiles in batches."""
        all_messages = []

        for i in range(0, len(profiles), self.batch_size):
            batch = profiles[i:i + self.batch_size]
            logger.info(f"Generating outreach for batch {i//self.batch_size + 1} ({len(batch)} profiles)")

            tasks = [
                self.generator.generate_variants(
                    profile=profile,
                    template_type=template_type,
                    brand_name=brand_name,
                    brand_description=brand_description,
                    sender_name=sender_name,
                    sender_title=sender_title,
                    sender_email=sender_email,
                    custom_context=custom_context,
                )
                for profile in batch
                for template_type in template_types
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Batch generation error: {result}")
                elif isinstance(result, list):
                    all_messages.extend(result)

        return all_messages


async def generate_outreach(
    profiles: List[EnrichedProfile],
    brand_name: str,
    brand_description: str,
    sender_name: str,
    sender_email: str,
    template_types: Optional[List[OutreachType]] = None,
    variants_per_influencer: int = 3,
    api_key: Optional[str] = None,) -> List[OutreachMessage]:
    """Convenience function to generate outreach messages."""
    config = GenerationConfig(
        variants_per_influencer=variants_per_influencer,
    )
    generator = OutreachGenerator(config, api_key)

    if template_types is None:
        template_types = [OutreachType.COLLABORATION]

    all_messages = []
    for profile in profiles:
        for template_type in template_types:
            messages = await generator.generate_variants(
                profile=profile,
                template_type=template_type,
                brand_name=brand_name,
                brand_description=brand_description,
                sender_name=sender_name,
                sender_title="Partnerships Manager",
                sender_email=sender_email,
            )
            all_messages.extend(messages)

    return all_messages


__all__ = [
    "GenerationConfig",
    "GenerationResult",
    "OutreachGenerator",
    "BatchOutreachGenerator",
    "generate_outreach",
]
