"""
Configuration management for the Micro-Influencer Outreach System.
Loads settings from YAML files with environment variable overrides.
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from functools import lru_cache

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.models import Niche, Platform, OutreachType


class DiscoveryConfig(BaseSettings):
    """Discovery module configuration."""
    target_count: int = 50
    niches: List[Niche] = Field(default_factory=list)
    platforms: List[Platform] = Field(default_factory=list)
    rate_limits: Dict[str, int] = Field(default_factory=dict)
    max_concurrent: int = 5
    request_timeout: int = 30

    model_config = SettingsConfigDict(env_prefix="DISCOVERY_")


class FilterConfig(BaseSettings):
    """Filter module configuration."""
    min_followers: int = 5000
    max_followers: int = 100000
    min_engagement_rate: float = 0.02
    require_contact_info: bool = False
    min_posts: int = 10

    model_config = SettingsConfigDict(env_prefix="FILTER_")


class EnrichmentConfig(BaseSettings):
    """Enrichment module configuration."""
    extract_emails: bool = True
    analyze_recent_posts: int = 10
    check_cross_platform: bool = True
    resolve_link_in_bio: bool = True

    model_config = SettingsConfigDict(env_prefix="ENRICHMENT_")


class OutreachConfig(BaseSettings):
    """Outreach module configuration."""
    gemini_model: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 500
    variants_per_influencer: int = 3

    model_config = SettingsConfigDict(env_prefix="OUTREACH_")


class StorageConfig(BaseSettings):
    """Storage configuration."""
    database_path: str = "data/influencers.db"
    export_path: str = "data/results.json"

    model_config = SettingsConfigDict(env_prefix="STORAGE_")


class LoggingConfig(BaseSettings):
    """Logging configuration."""
    level: str = "INFO"
    file: str = "logs/outreach.log"

    model_config = SettingsConfigDict(env_prefix="LOGGING_")


class Settings(BaseSettings):
    """Main application settings."""
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    outreach: OutreachConfig = Field(default_factory=OutreachConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    gemini_api_key: Optional[str] = Field(None, alias="GEMINI_API_KEY")
    youtube_api_key: Optional[str] = Field(None, alias="YOUTUBE_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


class NicheKeywords:
    """Niche keyword definitions loaded from YAML."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "niches.yaml"

        self.config_path = config_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load niche keywords from YAML file."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {"niches": {}}

    def get_keywords(self, niche: Niche) -> List[str]:
        """Get keywords for a niche."""
        niche_data = self._data.get("niches", {}).get(niche.value, {})
        return niche_data.get("keywords", [])

    def get_hashtags(self, niche: Niche) -> List[str]:
        """Get hashtags for a niche."""
        niche_data = self._data.get("niches", {}).get(niche.value, {})
        return niche_data.get("hashtags", [])

    def get_niche_name(self, niche: Niche) -> str:
        """Get display name for a niche."""
        niche_data = self._data.get("niches", {}).get(niche.value, {})
        return niche_data.get("name", niche.value.title())

    def all_niches(self) -> List[Niche]:
        """Get all configured niches."""
        return [Niche(n) for n in self._data.get("niches", {}).keys()]

    def search_niche(self, text: str, threshold: int = 2) -> List[Niche]:
        """Find matching niches based on keyword occurrence in text."""
        text_lower = text.lower()
        matches = []

        for niche in Niche:
            keywords = self.get_keywords(niche)
            count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if count >= threshold:
                matches.append((niche, count))

        matches.sort(key=lambda x: x[1], reverse=True)
        return [niche for niche, _ in matches]


class OutreachTemplates:
    """Outreach templates loaded from YAML."""

    def __init__(self, config_path: Optional[Path] = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config" / "templates" / "outreach_templates.yaml"

        self.config_path = config_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load templates from YAML file."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
        else:
            self._data = {"templates": {}, "defaults": {}}

    def get_template(self, template_type: OutreachType) -> Optional[Dict[str, Any]]:
        """Get template by type."""
        return self._data.get("templates", {}).get(template_type.value)

    def get_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """Get all templates."""
        return self._data.get("templates", {})

    def get_defaults(self) -> Dict[str, Any]:
        """Get default template values."""
        return self._data.get("defaults", {})

    def get_template_names(self) -> List[str]:
        """Get list of available template names."""
        return list(self._data.get("templates", {}).keys())


_settings: Optional[Settings] = None
_niche_keywords: Optional[NicheKeywords] = None
_outreach_templates: Optional[OutreachTemplates] = None


def get_settings() -> Settings:
    """Get global settings instance (singleton)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_niche_keywords() -> NicheKeywords:
    """Get global niche keywords instance (singleton)."""
    global _niche_keywords
    if _niche_keywords is None:
        _niche_keywords = NicheKeywords()
    return _niche_keywords


def get_outreach_templates() -> OutreachTemplates:
    """Get global outreach templates instance (singleton)."""
    global _outreach_templates
    if _outreach_templates is None:
        _outreach_templates = OutreachTemplates()
    return _outreach_templates


def reload_config() -> None:
    """Reload all configuration (useful for testing)."""
    global _settings, _niche_keywords, _outreach_templates
    _settings = None
    _niche_keywords = None
    _outreach_templates = None
    get_settings()
    get_niche_keywords()
    get_outreach_templates()


def setup_directories() -> None:
    """Create necessary directories if they don't exist."""
    dirs = [
        "data",
        "logs",
        "data/exports",
    ]
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


setup_directories()