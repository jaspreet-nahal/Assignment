#!/usr/bin/env python
"""
Standalone pipeline runner - bypasses Typer CLI issues.
Run the full micro-influencer outreach pipeline directly.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from src.core.config import setup_directories
from src.core.models import Niche, Platform, OutreachType
from src.discovery.manager import EnhancedDiscoveryManager, DiscoveryConfig
from src.filter.processor import FilterProcessor, ProcessorConfig, create_processor
from src.enrichment.manager import EnrichmentManager, EnrichmentConfig, enrich_influencers
from src.outreach.generator import OutreachGenerator, GenerationConfig, generate_outreach
from src.outreach.campaign import OutreachCampaign
from src.core.storage import initialize_database, get_exporter, get_pipeline_repo


async def run_quick_test():
    """Run a quick test with mock data."""
    print("=" * 60)
    print("QUICK TEST: Micro-Influencer Outreach Pipeline")
    print("=" * 60)

    # Configuration
    niches = [Niche.FITNESS, Niche.TECHNOLOGY]
    platforms = [Platform.INSTAGRAM, Platform.YOUTUBE]
    target_count = 10  # Per niche
    brand_name = "TestBrand"
    brand_description = "a test brand for pipeline verification"
    sender_name = "Test Sender"
    sender_email = "test@testbrand.com"
    template_types = [OutreachType.COLLABORATION_PROPOSAL, OutreachType.PRODUCT_SEEDING]
    variants = 2
    use_ai = False  # No API key needed for test
    save_db = False

    print(f"\nConfiguration:")
    print(f"  Niches: {[n.value for n in niches]}")
    print(f"  Platforms: {[p.value for p in platforms]}")
    print(f"  Target per niche: {target_count}")
    print(f"  Mock mode: True")
    print(f"  AI mode: {use_ai}")

    # Stage 1: Discovery
    print("\n[Stage 1/4] Discovery...")
    config = DiscoveryConfig(
        niches=niches,
        platforms=platforms,
        target_count=target_count * len(niches),
        use_mock=True,
        youtube_api_key=None,
    )

    manager = EnhancedDiscoveryManager(config)
    try:
        discovery_result = await manager.discover()
        print(f"  Found {discovery_result.influencers_found} influencers")
    finally:
        await manager.close()

    # Stage 2: Filtering
    print("\n[Stage 2/4] Filtering...")
    processor = create_processor(
        min_followers=5000,
        max_followers=100000,
        min_engagement_rate=0.02,
    )

    filter_result = processor.process(discovery_result.influencers)
    print(f"  Passed: {filter_result.filter_result.passed_count}/{filter_result.filter_result.input_count}")

    # Stage 3: Enrichment
    print("\n[Stage 3/4] Enrichment...")
    enrichment_config = EnrichmentConfig(
        analyze_recent_posts=5,
        check_cross_platform=True,
        extract_emails=True,
    )

    enriched_profiles = await enrich_influencers(filter_result.passed_influencers, enrichment_config)
    print(f"  Enriched: {len(enriched_profiles)} profiles")

    # Stage 4: Outreach
    print("\n[Stage 4/4] Outreach Generation...")
    gen_config = GenerationConfig(
        variants_per_influencer=variants,
        use_ai=use_ai,
    )
    generator = OutreachGenerator(gen_config)

    all_messages = []
    for profile in enriched_profiles:
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

    print(f"  Generated: {len(all_messages)} messages")

    # Save results
    output_file = "test_results.json"
    exporter = get_exporter()
    filepath = exporter.export_influencers(enriched_profiles, "enriched_profiles.json")

    # Export messages
    import json
    messages_data = [msg.model_dump(mode="json") for msg in all_messages]
    with open(output_file, "w") as f:
        json.dump(messages_data, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print("TEST COMPLETE!")
    print(f"{'=' * 60}")
    print(f"Discovered: {discovery_result.influencers_found}")
    print(f"Filtered: {filter_result.filter_result.passed_count}")
    print(f"Enriched: {len(enriched_profiles)}")
    print(f"Messages: {len(all_messages)}")
    print(f"Results saved to: {output_file}")
    print(f"Enriched profiles saved to: enriched_profiles.json")

    # Print sample message
    if all_messages:
        print(f"\n--- Sample Message ---")
        msg = all_messages[0]
        print(f"To: {msg.influencer_id[:8]}")
        print(f"Subject: {msg.subject}")
        print(f"Body preview: {msg.body[:200]}...")

    return True


async def run_full_pipeline(
    niches_list=None,
    platforms_list=None,
    target_per_niche=50,
    use_mock=True,
    use_ai=False,
    brand_name="YourBrand",
    brand_description="an innovative brand",
    sender_name="Partnerships Team",
    sender_email="partnerships@brand.com",
    template_types_list=None,
    variants=3,
    save_db=False,
    output_file="results.json"
):
    """Run the full pipeline with custom configuration."""
    print("=" * 60)
    print("FULL PIPELINE: Micro-Influencer Outreach")
    print("=" * 60)

    # Defaults
    if niches_list is None:
        niches_list = [Niche.FITNESS, Niche.TECHNOLOGY]
    if platforms_list is None:
        platforms_list = [Platform.INSTAGRAM, Platform.YOUTUBE]
    if template_types_list is None:
        template_types_list = [OutreachType.COLLABORATION_PROPOSAL]

    print(f"\nConfiguration:")
    print(f"  Niches: {[n.value for n in niches_list]}")
    print(f"  Platforms: {[p.value for p in platforms_list]}")
    print(f"  Target per niche: {target_per_niche}")
    print(f"  Mock mode: {use_mock}")
    print(f"  AI mode: {use_ai}")
    print(f"  Brand: {brand_name}")

    # Initialize database if needed
    if save_db:
        await initialize_database()

    # Stage 1: Discovery
    print("\n[Stage 1/4] Discovery...")
    config = DiscoveryConfig(
        niches=niches_list,
        platforms=platforms_list,
        target_count=target_per_niche * len(niches_list),
        use_mock=use_mock,
        youtube_api_key=None,
    )

    manager = EnhancedDiscoveryManager(config)
    try:
        discovery_result = await manager.discover()
        print(f"  Found {discovery_result.influencers_found} influencers")
    finally:
        await manager.close()

    # Stage 2: Filtering
    print("\n[Stage 2/4] Filtering...")
    processor = create_processor(
        min_followers=5000,
        max_followers=100000,
        min_engagement_rate=0.02,
    )

    filter_result = processor.process(discovery_result.influencers)
    print(f"  Passed: {filter_result.filter_result.passed_count}/{filter_result.filter_result.input_count}")

    # Stage 3: Enrichment
    print("\n[Stage 3/4] Enrichment...")
    enrichment_config = EnrichmentConfig(
        analyze_recent_posts=10,
        check_cross_platform=True,
        extract_emails=True,
    )

    enriched_profiles = await enrich_influencers(filter_result.passed_influencers, enrichment_config)
    print(f"  Enriched: {len(enriched_profiles)} profiles")

    # Stage 4: Outreach
    print("\n[Stage 4/4] Outreach Generation...")
    gen_config = GenerationConfig(
        variants_per_influencer=variants,
        use_ai=use_ai,
    )
    generator = OutreachGenerator(gen_config)

    all_messages = []
    for profile in enriched_profiles:
        for template_type in template_types_list:
            messages = await generator.generate_variants(
                profile=profile,
                template_type=template_type,
                brand_name=brand_name,
                brand_description=brand_description or f"an innovative brand in the {profile.niche.value} space",
                sender_name=sender_name,
                sender_title="Partnerships Manager",
                sender_email=sender_email,
            )
            all_messages.extend(messages)

    print(f"  Generated: {len(all_messages)} messages")

    # Save to database if requested
    if save_db:
        pipeline_run = OutreachCampaign(
            name=f"{brand_name} Outreach - {datetime.utcnow().strftime('%Y-%m-%d')}",
            brand_name=brand_name,
            niche=niches_list[0] if len(niches_list) == 1 else Niche.LIFESTYLE,
            messages=all_messages,
            status="draft",
        )
        # Note: Full pipeline run saving would require more setup
        print("  Database save: Skipped (requires full PipelineRun setup)")

    # Export results
    exporter = get_exporter()

    # Export enriched profiles
    profiles_file = exporter.export_influencers(enriched_profiles, "enriched_profiles.json")
    print(f"  Enriched profiles: {profiles_file}")

    # Export messages
    import json
    messages_data = [msg.model_dump(mode="json") for msg in all_messages]
    with open(output_file, "w") as f:
        json.dump(messages_data, f, indent=2, default=str)
    print(f"  Messages: {output_file}")

    print(f"\n{'=' * 60}")
    print("PIPELINE COMPLETE!")
    print(f"{'=' * 60}")
    print(f"Discovered: {discovery_result.influencers_found}")
    print(f"Filtered: {filter_result.filter_result.passed_count}")
    print(f"Enriched: {len(enriched_profiles)}")
    print(f"Messages: {len(all_messages)}")

    return True


def parse_niche_string(niche_str: str):
    """Parse comma-separated niche string to list of Niche enums."""
    if niche_str.lower() == "all":
        return list(Niche)
    niches = []
    for n in niche_str.split(","):
        n = n.strip().upper()
        try:
            niches.append(Niche[n])
        except KeyError:
            print(f"Unknown niche: {n}")
            return None
    return niches


def parse_platform_string(platform_str: str):
    """Parse comma-separated platform string to list of Platform enums."""
    if platform_str.lower() == "all":
        return [p for p in Platform if p != Platform.TIKTOK]
    platforms = []
    for p in platform_str.split(","):
        p = p.strip().upper()
        try:
            platforms.append(Platform[p])
        except KeyError:
            print(f"Unknown platform: {p}")
            return None
    return platforms


def parse_template_string(template_str: str):
    """Parse comma-separated template string to list of OutreachType enums."""
    templates = []
    for t in template_str.split(","):
        t = t.strip().upper()
        try:
            templates.append(OutreachType[t])
        except KeyError:
            print(f"Unknown template: {t}")
            return None
    return templates


if __name__ == "__main__":
    import sys

    setup_directories()

    if len(sys.argv) > 1 and sys.argv[1] == "full":
        # Full pipeline with custom args
        # Usage: python run_pipeline.py full --niches fitness,technology --platforms instagram,youtube --target 50 --mock --ai --brand "MyBrand" --output results.json
        import argparse
        parser = argparse.ArgumentParser(description="Run full pipeline")
        parser.add_argument("--niches", default="fitness,technology")
        parser.add_argument("--platforms", default="instagram,youtube")
        parser.add_argument("--target", type=int, default=50)
        parser.add_argument("--mock", action="store_true", default=True)
        parser.add_argument("--real", action="store_true", help="Use real API (disables mock)")
        parser.add_argument("--ai", action="store_true", default=False)
        parser.add_argument("--brand", default="YourBrand")
        parser.add_argument("--description", default="")
        parser.add_argument("--sender-name", default="Partnerships Team")
        parser.add_argument("--sender-email", default="partnerships@brand.com")
        parser.add_argument("--templates", default="collaboration_proposal")
        parser.add_argument("--variants", type=int, default=3)
        parser.add_argument("--db", action="store_true", default=False)
        parser.add_argument("--output", default="results.json")

        args = parser.parse_args(sys.argv[2:])

        if args.real:
            args.mock = False

        niches = parse_niche_string(args.niches)
        platforms = parse_platform_string(args.platforms)
        templates = parse_template_string(args.templates)

        if niches and platforms and templates:
            asyncio.run(run_full_pipeline(
                niches_list=niches,
                platforms_list=platforms,
                target_per_niche=args.target,
                use_mock=args.mock,
                use_ai=args.ai,
                brand_name=args.brand,
                brand_description=args.description,
                sender_name=args.sender_name,
                sender_email=args.sender_email,
                template_types_list=templates,
                variants=args.variants,
                save_db=args.db,
                output_file=args.output
            ))
        else:
            print("Invalid niches, platforms, or templates")
            sys.exit(1)
    else:
        # Quick test
        asyncio.run(run_quick_test())