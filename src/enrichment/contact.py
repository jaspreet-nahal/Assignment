"""
Contact information extraction for influencer enrichment.
Extracts emails, phones, and business contact info from profiles and link-in-bio pages.
"""
import logging
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup
from src.core.models import InfluencerBase, ContactInfo, Platform
from src.enrichment.base import (
    EnrichmentBase,
    extract_emails,
    extract_phone,
    is_link_in_bio_platform,
    resolve_link_in_bio,
)

logger = logging.getLogger(__name__)


class ContactEnricher(EnrichmentBase):
    """Extracts contact information from influencer profiles and link-in-bio pages."""

    def __init__(self, platform: Platform = Platform.INSTAGRAM, **kwargs):
        super().__init__(platform, **kwargs)

        self.business_email_patterns = [
            r'\b(business|collab|collabs|partnership|partnerships|inquiries|inquiry|contact|info|hello|work|brand|sponsor|ad|ads|promo|marketing|pr|media)\s*@',
            r'@\s*(business|collab|collabs|partnership|partnerships|inquiries|inquiry|contact|info|hello|work|brand|sponsor|ad|ads|promo|marketing|pr|media)\b',
        ]

        self.link_in_bio_domains = {
            "linktr.ee", "linktree.com", "beacons.ai", "beacons.page",
            "campsite.bio", "linkin.bio", "bio.link", "kite.link",
            "tap.bio", "milkshake.app", "contactin.bio", "shorby.com",
            "lnk.bio", "allmylinks.com", "linkinbio.com", "lnk.bio",
        }

    async def enrich_contact(self, influencer: InfluencerBase) -> ContactInfo:
        """
        Main entry point for contact enrichment.
        Extracts emails from bio, external URL, and link-in-bio pages.
        """
        emails_found = []
        business_inquiry_email = None
        link_in_bio_url = None
        link_in_bio_platform = None
        social_links = {}
        phone = None
        confidence = 0.0

        if influencer.bio:
            bio_emails = extract_emails(influencer.bio)
            emails_found.extend(bio_emails)

            bio_phones = extract_phone(influencer.bio)
            if bio_phones and not phone:
                phone = bio_phones[0]

            business_email = self._find_business_email(bio_emails, influencer.bio)
            if business_email:
                business_inquiry_email = business_email

        if influencer.external_url:
            ext_url_str = str(influencer.external_url)
            link_in_bio_url = ext_url_str
            link_in_bio_platform = is_link_in_bio_platform(ext_url_str)

            link_data = await resolve_link_in_bio(ext_url_str, self.client)
            emails_found.extend(link_data["emails"])
            social_links.update(link_data["social_links"])

            for email in link_data["emails"]:
                if self._is_business_email(email):
                    business_inquiry_email = email
                    break

        platform_emails = await self._extract_platform_emails(influencer)
        emails_found.extend(platform_emails)

        emails_found = self._deduplicate_emails(emails_found)
        emails_found = [e for e in emails_found if self._is_valid_email(e)]

        primary_email = self._select_primary_email(emails_found, business_inquiry_email)

        confidence = self._calculate_confidence(
            emails_found, business_inquiry_email, link_in_bio_url, influencer
        )

        return ContactInfo(
            email=primary_email,
            emails_found=emails_found,
            phone=phone,
            link_in_bio_url=influencer.external_url,
            link_in_bio_platform=link_in_bio_platform,
            social_links=social_links,
            business_inquiry_email=business_inquiry_email,
            extracted_at=datetime.utcnow(),
            confidence=confidence,
        )

    async def _extract_platform_emails(self, influencer: InfluencerBase) -> List[str]:
        """Platform-specific email extraction (override in subclasses)."""
        return []

    def _find_business_email(self, emails: List[str], context: str) -> Optional[str]:
        """Find business/collab email from list."""
        for email in emails:
            if self._is_business_email(email):
                return email

        for pattern in self.business_email_patterns:
            match = re.search(pattern, context, re.IGNORECASE)
            if match:
                for email in emails:
                    if email.lower() in context.lower():
                        return email
        return None

    def _is_business_email(self, email: str) -> bool:
        """Check if email appears to be a business/inquiry email."""
        email_lower = email.lower()
        business_keywords = [
            "business", "collab", "collabs", "partnership", "partnerships",
            "inquiries", "inquiry", "contact", "work", "brand", "sponsor",
            "ad", "ads", "promo", "marketing", "pr", "media", "hello",
            "info", "management", "manager", "booking", "bookings"
        ]
        return any(keyword in email_lower for keyword in business_keywords)

    def _is_valid_email(self, email: str) -> bool:
        """Validate email format and filter out common false positives."""
        if not re.match(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$', email):
            return False

        false_positives = {
            "example.com", "test.com", "domain.com", "email.com",
            "yoursite.com", "yourdomain.com", "website.com",
            "noreply", "no-reply", "donotreply", "do-not-reply",
            "support@", "admin@", "root@", "postmaster@", "webmaster@",
        }

        email_lower = email.lower()
        for fp in false_positives:
            if fp in email_lower:
                return False

        local_part = email.split("@")[0]
        if len(local_part) < 2 or len(local_part) > 64:
            return False

        return True

    def _deduplicate_emails(self, emails: List[str]) -> List[str]:
        """Deduplicate emails case-insensitively, preserving order."""
        seen = set()
        unique = []
        for email in emails:
            email_lower = email.lower()
            if email_lower not in seen:
                seen.add(email_lower)
                unique.append(email)
        return unique

    def _select_primary_email(
        self,
        emails: List[str],
        business_email: Optional[str],
    ) -> Optional[str]:
        """Select the best primary email."""
        if not emails:
            return None

        if business_email and business_email in emails:
            return business_email

        generic_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com"}
        non_generic = [e for e in emails if e.split("@")[-1].lower() not in generic_domains]
        if non_generic:
            return non_generic[0]

        return emails[0]

    def _calculate_confidence(
        self,
        emails: List[str],
        business_email: Optional[str],
        link_in_bio_url: Optional[str],
        influencer: InfluencerBase,) -> float:
        """Calculate confidence in contact info accuracy."""
        confidence = 0.0

        if emails:
            confidence += 0.3

        if business_email:
            confidence += 0.3

        if link_in_bio_url:
            confidence += 0.2

        if influencer.verified:
            confidence += 0.1

        if influencer.raw_data.get("is_business_account", False):
            confidence += 0.1

        return min(confidence, 1.0)

    async def enrich_content(self, influencer: InfluencerBase, post_count: int = 10):
        """Not implemented in base contact enricher."""
        raise NotImplementedError("Use ContentEnricher for content analysis")

    async def enrich_cross_platform(self, influencer: InfluencerBase):
        """Not implemented in base contact enricher."""
        raise NotImplementedError("Use CrossPlatformEnricher for cross-platform analysis")


class InstagramContactEnricher(ContactEnricher):
    """Instagram-specific contact enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.INSTAGRAM, **kwargs)

    async def _extract_platform_emails(self, influencer: InfluencerBase) -> List[str]:
        """Extract emails from Instagram profile page."""
        emails = []

        try:
            if influencer.profile_url:
                response = await self._fetch(str(influencer.profile_url))
                soup = BeautifulSoup(response.text, "lxml")

                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    emails.extend(extract_emails(meta_desc["content"]))

                json_ld = soup.find("script", {"type": "application/ld+json"})
                if json_ld:
                    try:
                        import json
                        data = json.loads(json_ld.string)
                        if isinstance(data, dict) and "email" in data:
                            emails.append(data["email"])
                    except:
                        pass

                page_text = soup.get_text()
                emails.extend(extract_emails(page_text))

        except Exception as e:
            logger.warning(f"Failed to extract Instagram emails for @{influencer.username}: {e}")

        return emails


class YouTubeContactEnricher(ContactEnricher):
    """YouTube-specific contact enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.YOUTUBE, **kwargs)

    async def _extract_platform_emails(self, influencer: InfluencerBase) -> List[str]:
        """Extract emails from YouTube channel about page."""
        emails = []

        try:
            channel_id = influencer.raw_data.get("channel_id")
            if channel_id:
                about_url = f"https://www.youtube.com/channel/{channel_id}/about"
                response = await self._fetch(about_url)
                soup = BeautifulSoup(response.text, "lxml")

                page_text = soup.get_text()
                emails.extend(extract_emails(page_text))

                email_elements = soup.find_all("a", href=re.compile(r"mailto:"))
                for elem in email_elements:
                    href = elem.get("href", "")
                    if href.startswith("mailto:"):
                        emails.append(href[7:])  

        except Exception as e:
            logger.warning(f"Failed to extract YouTube emails for {influencer.username}: {e}")

        return emails


class TikTokContactEnricher(ContactEnricher):
    """TikTok-specific contact enrichment."""

    def __init__(self, **kwargs):
        super().__init__(Platform.TIKTOK, **kwargs)

    async def _extract_platform_emails(self, influencer: InfluencerBase) -> List[str]:
        """Extract emails from TikTok profile page."""
        emails = []

        try:
            if influencer.profile_url:
                response = await self._fetch(str(influencer.profile_url))
                soup = BeautifulSoup(response.text, "lxml")

                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc and meta_desc.get("content"):
                    emails.extend(extract_emails(meta_desc["content"]))

                page_text = soup.get_text()
                emails.extend(extract_emails(page_text))

        except Exception as e:
            logger.warning(f"Failed to extract TikTok emails for @{influencer.username}: {e}")

        return emails


def get_contact_enricher(platform: Platform, **kwargs) -> ContactEnricher:
    """Factory function to get platform-specific contact enricher."""
    enrichers = {
        Platform.INSTAGRAM: InstagramContactEnricher,
        Platform.YOUTUBE: YouTubeContactEnricher,
        Platform.TIKTOK: TikTokContactEnricher,
    }
    enricher_class = enrichers.get(platform, ContactEnricher)
    return enricher_class(**kwargs)


__all__ = [
    "ContactEnricher",
    "InstagramContactEnricher",
    "YouTubeContactEnricher",
    "TikTokContactEnricher",
    "get_contact_enricher",
]