import json
import sqlite3
import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar
from uuid import uuid4

from src.core.config import get_settings
from src.core.models import (
    InfluencerBase,
    EnrichedProfile,
    OutreachMessage,
    OutreachCampaign,
    DiscoveryResult,
    FilterResult,
    PipelineRun,
    Platform,
    Niche,
)


T = TypeVar("T")


class DatabaseManager:
    """Async SQLite database manager with connection pooling."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_settings().storage.database_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database tables."""
        if self._initialized:
            return

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS influencers (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    profile_url TEXT NOT NULL,
                    display_name TEXT,
                    bio TEXT,
                    follower_count INTEGER NOT NULL,
                    following_count INTEGER,
                    post_count INTEGER,
                    verified INTEGER DEFAULT 0,
                    profile_image_url TEXT,
                    external_url TEXT,
                    discovered_at TEXT NOT NULL,
                    discovery_method TEXT NOT NULL,
                    raw_data TEXT,
                    niche TEXT,
                    niche_confidence REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS enriched_profiles (
                    id TEXT PRIMARY KEY,
                    influencer_id TEXT NOT NULL REFERENCES influencers(id),
                    niche TEXT NOT NULL,
                    niche_confidence REAL,
                    engagement_data TEXT,
                    contact_data TEXT,
                    content_data TEXT,
                    cross_platform_data TEXT,
                    enrichment_version TEXT,
                    enriched_at TEXT NOT NULL,
                    enrichment_errors TEXT,
                    overall_score REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS outreach_messages (
                    id TEXT PRIMARY KEY,
                    influencer_id TEXT NOT NULL REFERENCES enriched_profiles(id),
                    template_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    variant INTEGER NOT NULL,
                    generated_at TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    tokens_used INTEGER,
                    personalization_context TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS outreach_campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    brand_name TEXT NOT NULL,
                    niche TEXT NOT NULL,
                    status TEXT DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS campaign_messages (
                    campaign_id TEXT NOT NULL REFERENCES outreach_campaigns(id),
                    message_id TEXT NOT NULL REFERENCES outreach_messages(id),
                    PRIMARY KEY (campaign_id, message_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    niches TEXT NOT NULL,
                    platforms TEXT NOT NULL,
                    target_count INTEGER NOT NULL,
                    discovery_data TEXT,
                    filter_data TEXT,
                    status TEXT DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    errors TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_influencers_platform ON influencers(platform)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_influencers_niche ON influencers(niche)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_influencers_followers ON influencers(follower_count)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_enriched_influencer ON enriched_profiles(influencer_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_outreach_influencer ON outreach_messages(influencer_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline_runs(status)")

            await db.commit()

        self._initialized = True

    @asynccontextmanager
    async def connection(self):
        """Get a database connection."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            yield db

    async def execute(self, query: str, params: tuple = ()) -> None:
        """Execute a query without returning results."""
        async with self.connection() as db:
            await db.execute(query, params)
            await db.commit()

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """Fetch a single row."""
        async with self.connection() as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchone()

    async def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """Fetch all rows."""
        async with self.connection() as db:
            cursor = await db.execute(query, params)
            return await cursor.fetchall()


class JSONExporter:
    """Export data to JSON files."""

    def __init__(self, export_dir: Optional[str] = None):
        self.export_dir = Path(export_dir or get_settings().storage.export_path).parent
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_influencers(self, influencers: List[InfluencerBase], filename: str = "influencers.json") -> Path:
        """Export influencers to JSON."""
        data = [inf.model_dump(mode="json") for inf in influencers]
        filepath = self.export_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def export_enriched_profiles(self, profiles: List[EnrichedProfile], filename: str = "enriched_profiles.json") -> Path:
        """Export enriched profiles to JSON."""
        data = [profile.model_dump(mode="json") for profile in profiles]
        filepath = self.export_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def export_outreach_campaign(self, campaign: OutreachCampaign, filename: Optional[str] = None) -> Path:
        """Export outreach campaign to JSON."""
        if filename is None:
            filename = f"campaign_{campaign.id[:8]}.json"
        data = campaign.model_dump(mode="json")
        filepath = self.export_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def export_pipeline_run(self, run: PipelineRun, filename: Optional[str] = None) -> Path:
        """Export full pipeline run to JSON."""
        if filename is None:
            filename = f"pipeline_{run.id[:8]}.json"
        data = run.model_dump(mode="json")
        filepath = self.export_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return filepath

    def export_results_summary(self, run: PipelineRun, filename: str = "results.json") -> Path:
        """Export a summary of results for easy consumption."""
        summary = {
            "pipeline_id": run.id,
            "pipeline_name": run.name,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_seconds": run.duration_seconds,
            "target_count": run.target_count,
            "actual_count": len(run.enriched_profiles),
            "success_rate": run.success_rate,
            "niches": [n.value for n in run.niches],
            "platforms": [p.value for p in run.platforms],
            "influencers": [
                {
                    "id": p.id,
                    "username": p.influencer.username,
                    "platform": p.influencer.platform.value,
                    "display_name": p.influencer.display_name,
                    "follower_count": p.influencer.follower_count,
                    "niche": p.niche.value,
                    "niche_confidence": p.niche_confidence,
                    "engagement_rate": p.engagement.engagement_rate,
                    "engagement_rate_percent": p.engagement.engagement_rate_percent,
                    "overall_score": p.overall_score,
                    "has_email": bool(p.contact.email),
                    "profile_url": str(p.influencer.profile_url),
                    "outreach_variants": len([m for m in run.outreach_campaigns
                                               for msg in m.messages
                                               if msg.influencer_id == p.id]),
                }
                for p in run.enriched_profiles
            ],
            "campaigns": [
                {
                    "id": c.id,
                    "name": c.name,
                    "brand_name": c.brand_name,
                    "niche": c.niche.value,
                    "status": c.status,
                    "total_messages": c.total_messages,
                    "unique_influencers": c.unique_influencers,
                }
                for c in run.outreach_campaigns
            ],
            "errors": run.errors,
        }
        filepath = self.export_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
        return filepath


class InfluencerRepository:
    """Repository for influencer data operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def save_influencer(self, influencer: InfluencerBase) -> str:
        """Save or update an influencer."""
        influencer_id = str(uuid4())
        await self.db.execute("""
            INSERT INTO influencers (
                id, username, platform, profile_url, display_name, bio,
                follower_count, following_count, post_count, verified,
                profile_image_url, external_url, discovered_at,
                discovery_method, raw_data, niche, niche_confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            influencer_id,
            influencer.username,
            influencer.platform.value,
            str(influencer.profile_url),
            influencer.display_name,
            influencer.bio,
            influencer.follower_count,
            influencer.following_count,
            influencer.post_count,
            int(influencer.verified),
            str(influencer.profile_image_url) if influencer.profile_image_url else None,
            str(influencer.external_url) if influencer.external_url else None,
            influencer.discovered_at.isoformat(),
            influencer.discovery_method,
            json.dumps(influencer.raw_data, default=str),
            None,
            None,
        ))
        return influencer_id

    async def save_influencers_batch(self, influencers: List[InfluencerBase]) -> List[str]:
        """Save multiple influencers in a batch."""
        ids = []
        async with self.db.connection() as conn:
            for inf in influencers:
                influencer_id = str(uuid4())
                await conn.execute("""
                    INSERT INTO influencers (
                        id, username, platform, profile_url, display_name, bio,
                        follower_count, following_count, post_count, verified,
                        profile_image_url, external_url, discovered_at,
                        discovery_method, raw_data, niche, niche_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    influencer_id,
                    inf.username,
                    inf.platform.value,
                    str(inf.profile_url),
                    inf.display_name,
                    inf.bio,
                    inf.follower_count,
                    inf.following_count,
                    inf.post_count,
                    int(inf.verified),
                    str(inf.profile_image_url) if inf.profile_image_url else None,
                    str(inf.external_url) if inf.external_url else None,
                    inf.discovered_at.isoformat(),
                    inf.discovery_method,
                    json.dumps(inf.raw_data, default=str),
                    None,
                    None,
                ))
                ids.append(influencer_id)
            await conn.commit()
        return ids

    async def get_influencer(self, influencer_id: str) -> Optional[InfluencerBase]:
        """Get influencer by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM influencers WHERE id = ?", (influencer_id,)
        )
        if row:
            return self._row_to_influencer(row)
        return None

    async def get_influencers_by_niche(self, niche: Niche, limit: int = 100) -> List[InfluencerBase]:
        """Get influencers filtered by niche."""
        rows = await self.db.fetchall(
            "SELECT * FROM influencers WHERE niche = ? ORDER BY follower_count DESC LIMIT ?",
            (niche.value, limit)
        )
        return [self._row_to_influencer(row) for row in rows]

    async def get_micro_influencers(self, limit: int = 100) -> List[InfluencerBase]:
        """Get all micro-influencers (5k-100k followers)."""
        rows = await self.db.fetchall("""
            SELECT * FROM influencers
            WHERE follower_count BETWEEN 5000 AND 100000
            ORDER BY follower_count DESC
            LIMIT ?
        """, (limit,))
        return [self._row_to_influencer(row) for row in rows]

    async def update_niche(self, influencer_id: str, niche: Niche, confidence: float) -> None:
        """Update influencer niche classification."""
        await self.db.execute("""
            UPDATE influencers SET niche = ?, niche_confidence = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (niche.value, confidence, influencer_id))

    def _row_to_influencer(self, row: sqlite3.Row) -> InfluencerBase:
        """Convert database row to InfluencerBase model."""
        return InfluencerBase(
            username=row["username"],
            platform=Platform(row["platform"]),
            profile_url=row["profile_url"],
            display_name=row["display_name"],
            bio=row["bio"],
            follower_count=row["follower_count"],
            following_count=row["following_count"],
            post_count=row["post_count"],
            verified=bool(row["verified"]),
            profile_image_url=row["profile_image_url"],
            external_url=row["external_url"],
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            discovery_method=row["discovery_method"],
            raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
        )


class EnrichedProfileRepository:
    """Repository for enriched profile operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def save_profile(self, profile: EnrichedProfile) -> str:
        """Save or update an enriched profile."""
        await self.db.execute("""
            INSERT OR REPLACE INTO enriched_profiles (
                id, influencer_id, niche, niche_confidence,
                engagement_data, contact_data, content_data,
                cross_platform_data, enrichment_version, enriched_at,
                enrichment_errors, overall_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.id,
            profile.influencer.id if hasattr(profile.influencer, 'id') else None,
            profile.niche.value,
            profile.niche_confidence,
            json.dumps(profile.engagement.model_dump(mode="json"), default=str),
            json.dumps(profile.contact.model_dump(mode="json"), default=str),
            json.dumps(profile.content.model_dump(mode="json"), default=str),
            json.dumps(profile.cross_platform.model_dump(mode="json"), default=str),
            profile.enrichment_version,
            profile.enriched_at.isoformat(),
            json.dumps(profile.enrichment_errors),
            profile.overall_score,
        ))
        return profile.id

    async def get_profile(self, profile_id: str) -> Optional[EnrichedProfile]:
        """Get enriched profile by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM enriched_profiles WHERE id = ?", (profile_id,)
        )
        if row:
            return self._row_to_profile(row)
        return None

    async def get_profiles_by_niche(self, niche: Niche, limit: int = 100) -> List[EnrichedProfile]:
        """Get enriched profiles by niche."""
        rows = await self.db.fetchall(
            "SELECT * FROM enriched_profiles WHERE niche = ? ORDER BY overall_score DESC LIMIT ?",
            (niche.value, limit)
        )
        return [self._row_to_profile(row) for row in rows]

    async def get_top_profiles(self, limit: int = 50, min_score: float = 0) -> List[EnrichedProfile]:
        """Get top profiles by overall score."""
        rows = await self.db.fetchall("""
            SELECT * FROM enriched_profiles
            WHERE overall_score >= ?
            ORDER BY overall_score DESC
            LIMIT ?
        """, (min_score, limit))
        return [self._row_to_profile(row) for row in rows]

    def _row_to_profile(self, row: sqlite3.Row) -> EnrichedProfile:
        """Convert database row to EnrichedProfile model."""
        from src.core.models import EngagementMetrics, ContactInfo, ContentAnalysis, CrossPlatformPresence

        return EnrichedProfile(
            id=row["id"],
            influencer=InfluencerBase(
                username="",
                platform=Platform.INSTAGRAM,
                profile_url="https://example.com",
                follower_count=0,
                discovery_method="db",
            ),
            niche=Niche(row["niche"]),
            niche_confidence=row["niche_confidence"],
            engagement=EngagementMetrics.model_validate_json(row["engagement_data"]),
            contact=ContactInfo.model_validate_json(row["contact_data"]),
            content=ContentAnalysis.model_validate_json(row["content_data"]),
            cross_platform=CrossPlatformPresence.model_validate_json(row["cross_platform_data"]),
            enrichment_version=row["enrichment_version"],
            enriched_at=datetime.fromisoformat(row["enriched_at"]),
            enrichment_errors=json.loads(row["enrichment_errors"]) if row["enrichment_errors"] else [],
        )


class OutreachRepository:
    """Repository for outreach messages and campaigns."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def save_message(self, message: OutreachMessage) -> str:
        """Save an outreach message."""
        await self.db.execute("""
            INSERT INTO outreach_messages (
                id, influencer_id, template_type, subject, body,
                variant, generated_at, model_used, tokens_used, personalization_context
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message.id,
            message.influencer_id,
            message.template_type.value,
            message.subject,
            message.body,
            message.variant,
            message.generated_at.isoformat(),
            message.model_used,
            message.tokens_used,
            json.dumps(message.personalization_context, default=str),
        ))
        return message.id

    async def save_campaign(self, campaign: OutreachCampaign) -> str:
        """Save an outreach campaign with its messages."""
        await self.db.execute("""
            INSERT INTO outreach_campaigns (id, name, brand_name, niche, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            campaign.id,
            campaign.name,
            campaign.brand_name,
            campaign.niche.value,
            campaign.status,
            campaign.created_at.isoformat(),
        ))

        for message in campaign.messages:
            await self.save_message(message)
            await self.db.execute("""
                INSERT INTO campaign_messages (campaign_id, message_id) VALUES (?, ?)
            """, (campaign.id, message.id))

        return campaign.id

    async def get_campaign(self, campaign_id: str) -> Optional[OutreachCampaign]:
        """Get campaign with messages."""
        campaign_row = await self.db.fetchone(
            "SELECT * FROM outreach_campaigns WHERE id = ?", (campaign_id,)
        )
        if not campaign_row:
            return None

        message_rows = await self.db.fetchall("""
            SELECT m.* FROM outreach_messages m
            JOIN campaign_messages cm ON m.id = cm.message_id
            WHERE cm.campaign_id = ?
        """, (campaign_id,))

        messages = [self._row_to_message(row) for row in message_rows]

        return OutreachCampaign(
            id=campaign_row["id"],
            name=campaign_row["name"],
            brand_name=campaign_row["brand_name"],
            niche=Niche(campaign_row["niche"]),
            messages=messages,
            created_at=datetime.fromisoformat(campaign_row["created_at"]),
            status=campaign_row["status"],
        )

    def _row_to_message(self, row: sqlite3.Row) -> OutreachMessage:
        """Convert database row to OutreachMessage."""
        return OutreachMessage(
            id=row["id"],
            influencer_id=row["influencer_id"],
            template_type=OutreachType(row["template_type"]),
            subject=row["subject"],
            body=row["body"],
            variant=row["variant"],
            generated_at=datetime.fromisoformat(row["generated_at"]),
            model_used=row["model_used"],
            tokens_used=row["tokens_used"],
            personalization_context=json.loads(row["personalization_context"]) if row["personalization_context"] else {},
        )


class PipelineRepository:
    """Repository for pipeline run tracking."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def save_run(self, run: PipelineRun) -> str:
        """Save or update a pipeline run."""
        await self.db.execute("""
            INSERT OR REPLACE INTO pipeline_runs (
                id, name, niches, platforms, target_count,
                discovery_data, filter_data, status,
                started_at, completed_at, errors
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run.id,
            run.name,
            json.dumps([n.value for n in run.niches]),
            json.dumps([p.value for p in run.platforms]),
            run.target_count,
            json.dumps(run.discovery.model_dump(mode="json")) if run.discovery else None,
            json.dumps(run.filter.model_dump(mode="json")) if run.filter else None,
            run.status,
            run.started_at.isoformat(),
            run.completed_at.isoformat() if run.completed_at else None,
            json.dumps(run.errors),
        ))
        return run.id

    async def get_run(self, run_id: str) -> Optional[PipelineRun]:
        """Get pipeline run by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        )
        if row:
            return self._row_to_run(row)
        return None

    async def get_recent_runs(self, limit: int = 10) -> List[PipelineRun]:
        """Get recent pipeline runs."""
        rows = await self.db.fetchall(
            "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
            (limit,)
        )
        return [self._row_to_run(row) for row in rows]

    def _row_to_run(self, row: sqlite3.Row) -> PipelineRun:
        """Convert database row to PipelineRun."""
        return PipelineRun(
            id=row["id"],
            name=row["name"],
            niches=[Niche(n) for n in json.loads(row["niches"])] if row["niches"] else [],
            platforms=[Platform(p) for p in json.loads(row["platforms"])] if row["platforms"] else [],
            target_count=row["target_count"],
            discovery=DiscoveryResult.model_validate_json(row["discovery_data"]) if row["discovery_data"] else None,
            filter=FilterResult.model_validate_json(row["filter_data"]) if row["filter_data"] else None,
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            errors=json.loads(row["errors"]) if row["errors"] else [],
        )


_db_manager: Optional[DatabaseManager] = None
_json_exporter: Optional[JSONExporter] = None
_influencer_repo: Optional[InfluencerRepository] = None
_enriched_repo: Optional[EnrichedProfileRepository] = None
_outreach_repo: Optional[OutreachRepository] = None
_pipeline_repo: Optional[PipelineRepository] = None


def get_db() -> DatabaseManager:
    """Get global database manager."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_exporter() -> JSONExporter:
    """Get global JSON exporter."""
    global _json_exporter
    if _json_exporter is None:
        _json_exporter = JSONExporter()
    return _json_exporter


def get_influencer_repo() -> InfluencerRepository:
    """Get influencer repository."""
    global _influencer_repo
    if _influencer_repo is None:
        _influencer_repo = InfluencerRepository(get_db())
    return _influencer_repo


def get_enriched_repo() -> EnrichedProfileRepository:
    """Get enriched profile repository."""
    global _enriched_repo
    if _enriched_repo is None:
        _enriched_repo = EnrichedProfileRepository(get_db())
    return _enriched_repo


def get_outreach_repo() -> OutreachRepository:
    """Get outreach repository."""
    global _outreach_repo
    if _outreach_repo is None:
        _outreach_repo = OutreachRepository(get_db())
    return _outreach_repo


def get_pipeline_repo() -> PipelineRepository:
    """Get pipeline repository."""
    global _pipeline_repo
    if _pipeline_repo is None:
        _pipeline_repo = PipelineRepository(get_db())
    return _pipeline_repo


async def initialize_database() -> None:
    """Initialize database on startup."""
    await get_db().initialize()
