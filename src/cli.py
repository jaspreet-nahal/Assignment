import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel
from rich.logging import RichHandler
from src.core.config import get_settings, reload_config, setup_directories
from src.core.models import (
    Niche, Platform, OutreachType, PipelineRun, PipelineRequest,
    FilterRequest, EnrichRequest, OutreachRequest, OutreachCampaign,
)
from src.discovery.manager import EnhancedDiscoveryManager, DiscoveryConfig, run_discovery
from src.filter.processor import FilterProcessor, ProcessorConfig, create_processor
from src.enrichment.manager import EnrichmentManager, EnrichmentConfig, enrich_influencers
from src.outreach.generator import OutreachGenerator, GenerationConfig, generate_outreach
from src.outreach.campaign import CampaignManager, create_quick_campaign
from src.core.storage import initialize_database, get_exporter, get_pipeline_repo

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True, markup=True)],
)
logger = logging.getLogger(__name__)

# Setup directories
setup_directories()

# Rich console
console = Console()

# Typer app
app = typer.Typer(
    name="influencer-outreach",
    help="Automated Micro-Influencer Outreach System",
    add_completion=False,
    no_args_is_help=True,
)


def parse_niches(niche_str: str) -> List[Niche]:
    """Parse comma-separated niche string to list of Niche enums."""
    if niche_str.lower() == "all":
        return list(Niche)
    niches = []
    for n in niche_str.split(","):
        n = n.strip().upper()
        try:
            niches.append(Niche[n])
        except KeyError:
            console.print(f"[red]Unknown niche: {n}[/red]")
            raise typer.Exit(1)
    return niches


def parse_platforms(platform_str: str) -> List[Platform]:
    """Parse comma-separated platform string to list of Platform enums."""
    if platform_str.lower() == "all":
        return [p for p in Platform if p != Platform.TIKTOK]  # Exclude TikTok (banned in India)
    platforms = []
    for p in platform_str.split(","):
        p = p.strip().upper()
        try:
            platforms.append(Platform[p])
        except KeyError:
            console.print(f"[red]Unknown platform: {p}[/red]")
            raise typer.Exit(1)
    return platforms


@app.command()
def discover(
    niches: str = typer.Option("all", "--niches", "-n", help="Comma-separated niches (or 'all')"),
    platforms: str = typer.Option("instagram,youtube", "--platforms", "-p", help="Comma-separated platforms"),
    target_count: int = typer.Option(50, "--target", "-t", help="Target number of influencers"),
    use_mock: bool = typer.Option(False, "--mock", help="Use mock data (default: real API)"),
    youtube_api_key: Optional[str] = typer.Option(None, "--youtube-key", help="YouTube API key"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output JSON file"),
):
    """Run influencer discovery only."""
    async def _run():
        niche_list = parse_niches(niches)
        platform_list = parse_platforms(platforms)

        console.print(Panel.fit(
            f"[bold]Discovery Started[/bold]\n"
            f"Niches: {', '.join(n.value for n in niche_list)}\n"
            f"Platforms: {', '.join(p.value for p in platform_list)}\n"
            f"Target: {target_count} influencers\n"
            f"Mode: {'Mock' if use_mock else 'Real API'}",
            title="[Discovery]",
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Discovering influencers...", total=100)

            config = DiscoveryConfig(
                niches=niche_list,
                platforms=platform_list,
                target_count=target_count,
                use_mock=use_mock,
                youtube_api_key=youtube_api_key,
            )

            manager = EnhancedDiscoveryManager(config)
            try:
                result = await manager.discover()
                progress.update(task, completed=100)
            finally:
                await manager.close()

        # Display results
        table = Table(title=f"Discovery Results ({result.influencers_found} found)")
        table.add_column("Username", style="cyan")
        table.add_column("Platform", style="magenta")
        table.add_column("Followers", justify="right", style="green")
        table.add_column("Niche", style="yellow")
        table.add_column("Method", style="blue")

        for inf in result.influencers[:20]:  # Show first 20
            table.add_row(
                f"@{inf.username}",
                inf.platform.value,
                f"{inf.follower_count:,}",
                inf.raw_data.get("discovery_niche", "N/A"),
                inf.discovery_method,
            )

        console.print(table)

        if result.errors:
            console.print(f"[yellow]Errors: {len(result.errors)}[/yellow]")
            for err in result.errors[:5]:
                console.print(f"  - {err}")

        # Save results
        if output:
            exporter = get_exporter()
            filepath = exporter.export_influencers(result.influencers, output)
            console.print(f"[green]Results saved to {filepath}[/green]")

        return result

    return asyncio.run(_run())


@app.command()
def filter(
    input_file: str = typer.Argument(..., help="Input JSON file from discovery"),
    min_followers: int = typer.Option(5000, "--min-followers", help="Minimum followers"),
    max_followers: int = typer.Option(100000, "--max-followers", help="Maximum followers"),
    min_engagement: float = typer.Option(0.02, "--min-engagement", help="Minimum engagement rate"),
    require_contact: bool = typer.Option(False, "--require-contact", help="Require contact info"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output JSON file"),
):
    """Filter and classify discovered influencers."""
    async def _run():
        # Load influencers
        import json
        with open(input_file, "r") as f:
            data = json.load(f)

        from src.core.models import InfluencerBase
        influencers = [InfluencerBase(**item) for item in data]

        console.print(Panel.fit(
            f"[bold]Filtering Started[/bold]\n"
            f"Input: {len(influencers)} influencers\n"
            f"Followers: {min_followers:,} - {max_followers:,}\n"
            f"Min Engagement: {min_engagement:.1%}\n"
            f"Require Contact: {require_contact}",
            title="[Filtering]",
        ))

        processor = create_processor(
            min_followers=min_followers,
            max_followers=max_followers,
            min_engagement_rate=min_engagement,
            require_contact=require_contact,
        )

        result = processor.process(influencers)

        # Display results
        table = Table(title=f"Filter Results ({result.filter_result.passed_count}/{result.filter_result.input_count} passed)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Input Count", str(result.filter_result.input_count))
        table.add_row("Passed", str(result.filter_result.passed_count))
        table.add_row("Filtered", str(result.filter_result.filtered_count))
        table.add_row("Processing Time", f"{result.processing_time:.2f}s")

        if result.filter_result.filtered_reasons:
            table.add_row("Filter Reasons", ", ".join(f"{k}: {v}" for k, v in result.filter_result.filtered_reasons.items()))

        if result.filter_result.classified_niches:
            table.add_column("Niche", style="yellow")
            table.add_column("Count", style="green")
            for niche, count in result.filter_result.classified_niches.items():
                table.add_row(niche.value if hasattr(niche, 'value') else str(niche), str(count))

        console.print(table)

        # Save filtered influencers
        if output:
            exporter = get_exporter()
            filepath = exporter.export_influencers(result.passed_influencers, output)
            console.print(f"[green]Filtered influencers saved to {filepath}[/green]")

        return result

    return asyncio.run(_run())


@app.command()
def enrich(
    input_file: str = typer.Argument(..., help="Input JSON file from filtering"),
    analyze_posts: int = typer.Option(10, "--posts", help="Number of posts to analyze"),
    check_cross_platform: bool = typer.Option(False, "--cross-platform", help="Check cross-platform presence (default: false)"),
    extract_emails: bool = typer.Option(False, "--emails", help="Extract contact emails (default: false)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output JSON file"),
):
    """Enrich filtered influencer profiles."""
    async def _run():
        # Load influencers
        import json
        with open(input_file, "r") as f:
            data = json.load(f)

        from src.core.models import InfluencerBase
        influencers = [InfluencerBase(**item) for item in data]

        console.print(Panel.fit(
            f"[bold]Enrichment Started[/bold]\n"
            f"Input: {len(influencers)} influencers\n"
            f"Analyze Posts: {analyze_posts}\n"
            f"Cross-Platform: {check_cross_platform}\n"
            f"Extract Emails: {extract_emails}",
            title="[Enrichment]",
        ))

        config = EnrichmentConfig(
            extract_emails=extract_emails,
            analyze_recent_posts=analyze_posts,
            check_cross_platform=check_cross_platform,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Enriching profiles...", total=len(influencers))

            profiles = await enrich_influencers(influencers, config)

            progress.update(task, completed=len(influencers))

        # Display results
        table = Table(title=f"Enrichment Results ({len(profiles)} profiles)")
        table.add_column("Username", style="cyan")
        table.add_column("Niche", style="magenta")
        table.add_column("Confidence", justify="right", style="green")
        table.add_column("Engagement", justify="right", style="yellow")
        table.add_column("Email", style="blue")
        table.add_column("Score", justify="right", style="bold green")

        for profile in profiles[:20]:
            table.add_row(
                f"@{profile.influencer.username}",
                profile.niche.value,
                f"{profile.niche_confidence:.0%}",
                f"{profile.engagement.engagement_rate_percent:.1f}%",
                "✓" if profile.contact.email else "✗",
                f"{profile.overall_score:.1f}",
            )

        console.print(table)

        # Stats
        stats = {
            "with_email": sum(1 for p in profiles if p.contact.email),
            "with_cross_platform": sum(1 for p in profiles if p.cross_platform.platform_count > 1),
            "brand_safe": sum(1 for p in profiles if p.content.brand_safe),
            "avg_score": sum(p.overall_score for p in profiles) / len(profiles) if profiles else 0,
        }

        console.print(f"\n[bold]Summary:[/bold]")
        console.print(f"  With Email: {stats['with_email']}/{len(profiles)}")
        console.print(f"  Multi-Platform: {stats['with_cross_platform']}/{len(profiles)}")
        console.print(f"  Brand Safe: {stats['brand_safe']}/{len(profiles)}")
        console.print(f"  Avg Score: {stats['avg_score']:.1f}")

        # Save results
        if output:
            exporter = get_exporter()
            filepath = exporter.export_enriched_profiles(profiles, output)
            console.print(f"[green]Enriched profiles saved to {filepath}[/green]")

        return profiles

    return asyncio.run(_run())


@app.command()
def outreach(
    input_file: str = typer.Argument(..., help="Input JSON file from enrichment"),
    brand_name: str = typer.Option(..., "--brand", "-b", help="Brand name"),
    brand_description: str = typer.Option("", "--description", "-d", help="Brand description"),
    sender_name: str = typer.Option("Partnerships Team", "--sender-name", help="Sender name"),
    sender_email: str = typer.Option("partnerships@brand.com", "--sender-email", help="Sender email"),
    template_types: str = typer.Option("collaboration_proposal", "--templates", help="Comma-separated template types"),
    variants: int = typer.Option(3, "--variants", "-v", help="Variants per influencer"),
    use_ai: bool = typer.Option(False, "--ai", help="Use AI generation (requires GEMINI_API_KEY, default: false)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output JSON file"),
):
    """Generate personalized outreach messages."""
    async def _run():
        # Load enriched profiles
        import json
        with open(input_file, "r") as f:
            data = json.load(f)

        from src.core.models import EnrichedProfile
        profiles = [EnrichedProfile(**item) for item in data]

        # Parse template types
        template_list = []
        for t in template_types.split(","):
            t = t.strip()
            try:
                template_list.append(OutreachType[t.upper()])
            except KeyError:
                console.print(f"[red]Unknown template type: {t}[/red]")
                raise typer.Exit(1)

        console.print(Panel.fit(
            f"[bold]Outreach Generation[/bold]\n"
            f"Profiles: {len(profiles)}\n"
            f"Brand: {brand_name}\n"
            f"Templates: {', '.join(t.value for t in template_list)}\n"
            f"Variants: {variants} per influencer\n"
            f"AI Mode: {'Enabled' if use_ai else 'Disabled (templates only)'}",
            title="[Outreach]",
        ))

        config = GenerationConfig(
            variants_per_influencer=variants,
            use_ai=use_ai,
        )
        generator = OutreachGenerator(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Generating messages...", total=len(profiles) * len(template_list))

            all_messages = []
            for profile in profiles:
                for template_type in template_list:
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
                    progress.advance(task)

        # Display sample
        table = Table(title=f"Generated Messages ({len(all_messages)} total)")
        table.add_column("Influencer", style="cyan")
        table.add_column("Template", style="magenta")
        table.add_column("Variant", justify="right")
        table.add_column("Subject", style="green")
        table.add_column("Model", style="blue")

        for msg in all_messages[:15]:
            table.add_row(
                msg.influencer_id[:8],
                msg.template_type.value,
                str(msg.variant),
                msg.subject[:50] + "..." if len(msg.subject) > 50 else msg.subject,
                msg.model_used,
            )

        console.print(table)

        # Save results
        if output:
            import json
            output_data = [msg.model_dump(mode="json") for msg in all_messages]
            with open(output, "w") as f:
                json.dump(output_data, f, indent=2, default=str)
            console.print(f"[green]Messages saved to {output}[/green]")

        return all_messages

    return asyncio.run(_run())


@app.command()
def pipeline(
    niches: str = typer.Option("all", "--niches", "-n", help="Comma-separated niches (or 'all')"),
    platforms: str = typer.Option("instagram,youtube", "--platforms", "-p", help="Comma-separated platforms (TikTok excluded)"),
    target_count: int = typer.Option(50, "--target", "-t", help="Target influencers per niche"),
    use_mock: bool = typer.Option(False, "--mock", help="Use mock discovery (default: real API)"),
    youtube_api_key: Optional[str] = typer.Option(None, "--youtube-key", help="YouTube API key"),
    min_followers: int = typer.Option(5000, "--min-followers", help="Min followers for filtering"),
    max_followers: int = typer.Option(100000, "--max-followers", help="Max followers for filtering"),
    min_engagement: float = typer.Option(0.02, "--min-engagement", help="Min engagement rate"),
    analyze_posts: int = typer.Option(10, "--posts", help="Posts to analyze for enrichment"),
    brand_name: str = typer.Option("YourBrand", "--brand", "-b", help="Brand name for outreach"),
    brand_description: str = typer.Option("", "--description", "-d", help="Brand description"),
    sender_name: str = typer.Option("Partnerships Team", "--sender-name", help="Sender name"),
    sender_email: str = typer.Option("partnerships@brand.com", "--sender-email", help="Sender email"),
    template_types: str = typer.Option("collaboration_proposal", "--templates", help="Outreach template types"),
    variants: int = typer.Option(3, "--variants", "-v", help="Variants per influencer"),
    use_ai: bool = typer.Option(False, "--ai", help="Use AI for outreach (default: false)"),
    output: str = typer.Option("results.json", "--output", "-o", help="Output file for final results"),
    save_db: bool = typer.Option(False, "--db", help="Save to database (default: false)"),
):
    """Run full end-to-end pipeline: discover -> filter -> enrich -> outreach."""
    async def _run():
        start_time = datetime.utcnow()
        niche_list = parse_niches(niches)
        platform_list = parse_platforms(platforms)

        # Parse template types
        template_list = []
        for t in template_types.split(","):
            t = t.strip()
            try:
                template_list.append(OutreachType[t.upper()])
            except KeyError:
                console.print(f"[red]Unknown template type: {t}[/red]")
                raise typer.Exit(1)

        console.print(Panel.fit(
            f"[bold]Full Pipeline Started[/bold]\n"
            f"Niches: {', '.join(n.value for n in niche_list)}\n"
            f"Platforms: {', '.join(p.value for p in platform_list)}\n"
            f"Target: {target_count} per niche\n"
            f"Brand: {brand_name}\n"
            f"Output: {output}",
            title="[Pipeline]",
        ))

        # Initialize database if requested
        if save_db:
            await initialize_database()

        pipeline_run = PipelineRun(
            name=f"pipeline_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            niches=niche_list,
            platforms=platform_list,
            target_count=target_count,
        )

        # Stage 1: Discovery
        console.print("\n[bold cyan]Stage 1: Discovery[/bold cyan]")
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            task = progress.add_task("Discovering influencers...", total=None)

            config = DiscoveryConfig(
                niches=niche_list,
                platforms=platform_list,
                target_count=target_count * len(niche_list),  # Total target
                use_mock=use_mock,
                youtube_api_key=youtube_api_key,
            )

            manager = EnhancedDiscoveryManager(config)
            try:
                discovery_result = await manager.discover()
                pipeline_run.discovery = discovery_result
            finally:
                await manager.close()

        console.print(f"  Found {discovery_result.influencers_found} influencers")

        # Stage 2: Filtering
        console.print("\n[bold cyan]Stage 2: Filtering[/bold cyan]")
        processor = create_processor(
            min_followers=min_followers,
            max_followers=max_followers,
            min_engagement_rate=min_engagement,
        )

        filter_result = processor.process(discovery_result.influencers)
        pipeline_run.filter = filter_result.filter_result

        console.print(f"  Passed: {filter_result.filter_result.passed_count}/{filter_result.filter_result.input_count}")

        # Stage 3: Enrichment
        console.print("\n[bold cyan]Stage 3: Enrichment[/bold cyan]")
        enrichment_config = EnrichmentConfig(
            analyze_recent_posts=analyze_posts,
            check_cross_platform=True,
            extract_emails=True,
        )

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            task = progress.add_task("Enriching profiles...", total=None)
            enriched_profiles = await enrich_influencers(filter_result.passed_influencers, enrichment_config)
            pipeline_run.enriched_profiles = enriched_profiles

        console.print(f"  Enriched: {len(enriched_profiles)} profiles")

        # Stage 4: Outreach
        console.print("\n[bold cyan]Stage 4: Outreach Generation[/bold cyan]")
        gen_config = GenerationConfig(
            variants_per_influencer=variants,
            use_ai=use_ai,
        )
        generator = OutreachGenerator(gen_config)

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:
            task = progress.add_task("Generating outreach...", total=len(enriched_profiles) * len(template_list))

            all_messages = []
            for profile in enriched_profiles:
                for template_type in template_list:
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
                    progress.advance(task)

        # Create campaign
        campaign = OutreachCampaign(
            name=f"{brand_name} Outreach - {datetime.utcnow().strftime('%Y-%m-%d')}",
            brand_name=brand_name,
            niche=niche_list[0] if len(niche_list) == 1 else Niche.LIFESTYLE,
            messages=all_messages,
            status="draft",
        )
        pipeline_run.outreach_campaigns = [campaign]

        console.print(f"  Generated: {len(all_messages)} messages ({len(enriched_profiles)} influencers × {len(template_list)} templates × {variants} variants)")

        # Finalize pipeline run
        pipeline_run.completed_at = datetime.utcnow()
        pipeline_run.status = "completed"

        # Save to database
        if save_db:
            repo = get_pipeline_repo()
            await repo.save_run(pipeline_run)
            console.print("\n[green]Pipeline run saved to database[/green]")

        # Export results
        exporter = get_exporter()
        filepath = exporter.export_results_summary(pipeline_run, output)
        console.print(f"\n[green]Results exported to {filepath}[/green]")

        # Final summary
        duration = (pipeline_run.completed_at - start_time).total_seconds()
        console.print(Panel.fit(
            f"[bold green]Pipeline Complete![/bold green]\n"
            f"Duration: {duration:.1f}s\n"
            f"Discovered: {discovery_result.influencers_found}\n"
            f"Filtered: {filter_result.filter_result.passed_count}\n"
            f"Enriched: {len(enriched_profiles)}\n"
            f"Messages: {len(all_messages)}\n"
            f"Success Rate: {pipeline_run.success_rate:.1f}%",
            title="[Done]",
        ))

        return pipeline_run

    return asyncio.run(_run())


@app.command()
def status(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of recent runs to show"),
):
    """Show recent pipeline runs."""
    async def _run():
        await initialize_database()
        repo = get_pipeline_repo()
        runs = await repo.get_recent_runs(limit)

        if not runs:
            console.print("[yellow]No pipeline runs found[/yellow]")
            return

        table = Table(title=f"Recent Pipeline Runs ({len(runs)})")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Niches", style="yellow")
        table.add_column("Discovered", justify="right")
        table.add_column("Enriched", justify="right")
        table.add_column("Messages", justify="right")
        table.add_column("Duration", justify="right")
        table.add_column("Started", style="blue")

        for run in runs:
            table.add_row(
                run.id[:8],
                run.name,
                run.status,
                ", ".join(n.value for n in run.niches),
                str(run.discovery.influencers_found if run.discovery else 0),
                str(len(run.enriched_profiles)),
                str(sum(c.total_messages for c in run.outreach_campaigns)),
                f"{run.duration_seconds:.1f}s" if run.duration_seconds else "N/A",
                run.started_at.strftime("%Y-%m-%d %H:%M"),
            )

        console.print(table)

    return asyncio.run(_run())


@app.command()
def export(
    run_id: str = typer.Argument(..., help="Pipeline run ID"),
    format: str = typer.Option("json", "--format", "-f", help="Export format (json/csv)"),
):
    """Export pipeline run results."""
    async def _run():
        await initialize_database()
        repo = get_pipeline_repo()
        run = await repo.get_run(run_id)

        if not run:
            console.print(f"[red]Run not found: {run_id}[/red]")
            raise typer.Exit(1)

        exporter = get_exporter()

        if format == "json":
            filepath = exporter.export_pipeline_run(run)
        elif format == "csv":
            # Export campaign messages to CSV
            for campaign in run.outreach_campaigns:
                filepath = exporter.export_dir / f"campaign_{campaign.id[:8]}.csv"
                # Would implement CSV export
        else:
            console.print(f"[red]Unknown format: {format}[/red]")
            raise typer.Exit(1)

        console.print(f"[green]Exported to {filepath}[/green]")

    return asyncio.run(_run())


@app.command()
def test(
    quick: bool = typer.Option(False, "--quick", "-q", help="Quick test with minimal data"),
):
    """Run a quick test of the full pipeline with mock data."""
    console.print(Panel.fit(
        "[bold]Running Pipeline Test[/bold]\n"
        "This will run the full pipeline with mock data to verify everything works.",
        title="[Test]",
    ))

    # Run pipeline with minimal settings by calling the internal async function
    # We need to invoke the pipeline command logic directly
    import sys
    # Create a context and invoke the pipeline command
    from typer.testing import CliRunner
    runner = CliRunner()

    args = [
        "pipeline",
        "--niches", "fitness,technology" if quick else "all",
        "--platforms", "instagram,youtube",
        "--target", str(10 if quick else 50),
        "--mock",
        "--min-followers", "5000",
        "--max-followers", "100000",
        "--min-engagement", "0.02",
        "--posts", "5",
        "--brand", "TestBrand",
        "--description", "a test brand for pipeline verification",
        "--sender-name", "Test Sender",
        "--sender-email", "test@testbrand.com",
        "--templates", "collaboration_proposal,product_seeding",
        "--variants", "2",
        "--output", "test_results.json",
    ]

    result = runner.invoke(app, args)
    console.print(result.output)
    if result.exception:
        raise result.exception


@app.command()
def templates(
    list_templates: bool = typer.Option(True, "--list", "-l", help="List available templates"),
    preview: Optional[str] = typer.Option(None, "--preview", "-p", help="Preview specific template"),
):
    """Manage and preview outreach templates."""
    from src.outreach.templates import get_template_manager

    manager = get_template_manager()

    if list_templates:
        console.print(Panel.fit("[bold]Available Outreach Templates[/bold]", title="[Templates]"))
        for template_type in manager.get_all_template_types():
            validation = manager.validate_template(template_type)
            status = "[green]OK[/green]" if validation["valid"] else "[red]FAIL[/red]"
            console.print(f"  {status} {template_type.value}")

    if preview:
        try:
            template_type = OutreachType[preview.upper()]
            validation = manager.validate_template(template_type)
            if validation["valid"]:
                console.print(Panel(
                    f"[bold]Subject:[/bold] {validation['subject']}\n\n"
                    f"[bold]Body Preview:[/bold]\n{validation['body_preview']}...",
                    title=f"[Preview: {template_type.value}]",
                ))
            else:
                console.print(f"[red]Template invalid: {validation['error']}[/red]")
        except KeyError:
            console.print(f"[red]Unknown template: {preview}[/red]")


def main():
    """Main entry point."""
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("CLI error")
        sys.exit(1)


if __name__ == "__main__":
    main()
