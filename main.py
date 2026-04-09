#!/usr/bin/env python3
"""
Job Apply Bot — Main CLI
Usage: python main.py [command] [options]
"""

import asyncio
import json
import os
import sys
import random
from datetime import datetime
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

load_dotenv()

console = Console()


def load_config(config_path: str = "~/job-apply-bot/config.yaml") -> dict:
    path = Path(config_path).expanduser()
    if not path.exists():
        console.print(f"[red]Config not found: {path}[/red]")
        console.print("Copy config.yaml.example to config.yaml and fill in your details.")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def load_seen_urls(log_file: str = "~/job-apply/logs/seen_urls.json") -> set:
    path = Path(log_file).expanduser()
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_seen_urls(urls: set, log_file: str = "~/job-apply/logs/seen_urls.json"):
    path = Path(log_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(list(urls), f)


# ─── CLI COMMANDS ─────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Job Apply Bot — scrape, tailor, and apply to jobs automatically."""
    pass


@cli.command()
@click.option("--resume", required=True, help="Path to your resume PDF")
def extract_resume(resume):
    """Extract text from a PDF resume."""
    from resume_tailor import extract_resume_text
    text = extract_resume_text(resume)
    console.print(Panel(text[:3000] + ("..." if len(text) > 3000 else ""), title="Resume Text"))


@cli.command()
@click.option("--company", required=True, help="Company name")
@click.option("--role", required=True, help="Job title")
@click.option("--url", default="", help="Job posting URL (used as Apply link in sheet)")
@click.option("--location", default="", help="Job location (city, state or Remote)")
@click.option("--description", default="", help="Job description text (or pipe via stdin)")
@click.option("--description-file", default="", help="File containing job description")
@click.option("--field", default="", help="Override field: data_science|ml_ai|software_eng|neuroscience")
@click.option("--config", default="~/job-apply-bot/config.yaml", help="Config file path")
@click.option("--dry-run", is_flag=True, help="Tailor and preview but don't log to Sheets")
@click.option("--skip-location-check", is_flag=True, help="Bypass location filter")
def tailor(company, role, url, location, description, description_file, field, config, dry_run, skip_location_check):
    """Tailor your resume for a specific job and log it to Google Sheets."""
    cfg = load_config(config)

    # ── 1. Get job description ──────────────────────────────────────────────
    if description_file:
        with open(Path(description_file).expanduser()) as f:
            job_desc = f.read()
    elif description:
        job_desc = description
    elif not sys.stdin.isatty():
        job_desc = sys.stdin.read()
    else:
        console.print("[yellow]Paste job description then press Ctrl+D:[/yellow]")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        job_desc = "\n".join(lines)

    if not job_desc.strip():
        console.print("[red]No job description provided[/red]")
        sys.exit(1)

    # ── 2. Location filter ──────────────────────────────────────────────────
    if not skip_location_check and location:
        from src.location_filter import filter_location
        approved = filter_location(location, company, role)
        if not approved:
            console.print(f"[bold yellow]Skipping — location not in approved list.[/bold yellow]")
            console.print(f"  Add '{location}' to APPROVED_LOCATIONS in src/location_filter.py to include it.")
            console.print(f"  Or rerun with --skip-location-check to override.")
            # Log as filtered if sheets configured
            if not dry_run:
                sheets_cfg = cfg.get("google_sheets", {})
                if sheets_cfg.get("spreadsheet_id"):
                    from sheets_tracker import log_application
                    log_application(
                        spreadsheet_id=sheets_cfg["spreadsheet_id"],
                        sheet_name=sheets_cfg.get("sheet_name", "Applications"),
                        credentials_file=sheets_cfg.get("credentials_file", ""),
                        company=company, role=role, location=location,
                        field="", job_url=url, status="Filtered - Location",
                    )
            return

    # ── 3. Classify field → pick base resume ───────────────────────────────
    if field:
        field_key = field
        from src.field_classifier import FIELDS
        field_label = FIELDS.get(field_key, field_key)
    else:
        from src.field_classifier import classify_field
        field_key, field_label = classify_field(job_desc, role, company)

    console.print(f"[bold]Track:[/bold] {field_label}")

    # Load the base resume for this field
    from src.field_classifier import get_base_resume_path
    base_resume_rel = get_base_resume_path(field_key)
    base_resume_path = Path(base_resume_rel)
    if not base_resume_path.exists():
        # Try relative to script dir
        base_resume_path = Path(__file__).parent / base_resume_rel

    if not base_resume_path.exists():
        console.print(f"[red]Base resume not found: {base_resume_rel}[/red]")
        console.print("Populate resumes/base/ files first (see resumes/mega_resume.md)")
        sys.exit(1)

    with open(base_resume_path) as f:
        resume_text = f.read()

    # ── 4. Tailor via Claude ────────────────────────────────────────────────
    from resume_tailor import tailor_resume, save_tailored_resume

    result = tailor_resume(resume_text, job_desc, company, role, cfg)

    # ── 5. Display scores ───────────────────────────────────────────────────
    scores = result.get("scores", {})
    table = Table(title=f"Match Scores — {company} ({role})")
    table.add_column("Metric", style="cyan")
    table.add_column("Score", style="green")
    table.add_row("Skills Match",     f"{scores.get('skills_match', 'N/A')}/10")
    table.add_row("Experience Match", f"{scores.get('experience_match', 'N/A')}/10")
    table.add_row("Industry Match",   f"{scores.get('industry_match', 'N/A')}/10")
    table.add_row("Overall",          f"[bold]{scores.get('overall', 'N/A')}/10[/bold]")
    console.print(table)

    gaps = result.get("gaps", [])
    if gaps:
        console.print(f"[yellow]Gaps:[/yellow] {', '.join(gaps)}")

    skip_threshold = cfg.get("skip_if", {}).get("score_below", 0)
    overall_score = scores.get("overall", 10)
    if overall_score < skip_threshold:
        console.print(f"[yellow]Score {overall_score} below threshold {skip_threshold} — skipping[/yellow]")
        return

    # ── 6. Save tailored resume ─────────────────────────────────────────────
    output_dir = cfg.get("resume", {}).get("output_dir", "resumes/tailored")
    resume_file = save_tailored_resume(result["tailored_resume"], company, role, output_dir)
    resume_filename = Path(resume_file).name

    # ── 7. Log to Google Sheets ─────────────────────────────────────────────
    if not dry_run:
        sheets_cfg = cfg.get("google_sheets", {})
        if sheets_cfg.get("spreadsheet_id"):
            from sheets_tracker import log_application
            log_application(
                spreadsheet_id=sheets_cfg["spreadsheet_id"],
                sheet_name=sheets_cfg.get("sheet_name", "Applications"),
                credentials_file=sheets_cfg.get("credentials_file", ""),
                company=company,
                role=role,
                location=location,
                field=field_label,
                job_url=url,
                status="Tailored",
                scores=scores,
                gaps=gaps,
                ats_keywords=result.get("ats_keywords_added", []),
                resume_file=resume_filename,
            )

    # ── 8. Summary ──────────────────────────────────────────────────────────
    console.print(Panel(
        f"[bold green]Resume ready![/bold green]\n\n"
        f"[bold]File:[/bold]    {resume_file}\n"
        f"[bold]Field:[/bold]   {field_label}\n"
        f"[bold]Score:[/bold]   {scores.get('overall', '?')}/10\n"
        f"{'[bold]Apply:[/bold]   ' + url if url else '[dim]No apply URL provided[/dim]'}\n\n"
        f"[dim]Open the Google Sheet, find this row, click Apply, then change Status to 'Applied'.[/dim]",
        title=f"{company} — {role}"
    ))


@cli.command()
@click.option("--url", required=True, help="Job application URL")
@click.option("--resume", required=True, help="Path to tailored resume (.docx)")
@click.option("--company", default="", help="Company name (for logging)")
@click.option("--role", default="", help="Job role (for logging)")
@click.option("--platform", default="auto", help="Platform: auto|linkedin|indeed|greenhouse|lever|workday")
@click.option("--config", default="~/job-apply-bot/config.yaml")
@click.option("--dry-run", is_flag=True, help="Don't actually submit")
def apply(url, resume, company, role, platform, config, dry_run):
    """Apply to a single job."""
    cfg = load_config(config)
    asyncio.run(_apply_single(url, resume, company, role, platform, cfg, dry_run))


async def _apply_single(url, resume_path, company, role, platform, cfg, dry_run):
    from playwright.async_api import async_playwright
    from appliers.ats_applier import detect_ats, apply_ats
    from appliers.linkedin_applier import apply_linkedin_easy_apply
    from appliers.indeed_applier import apply_indeed_job, login_indeed
    from resume_tailor import generate_cover_letter

    cover_letter = generate_cover_letter("", company, role, cfg)

    # Auto-detect platform
    if platform == "auto":
        detected = detect_ats(url)
        if "linkedin.com" in url:
            platform = "linkedin"
        elif "indeed.com" in url:
            platform = "indeed"
        elif detected:
            platform = detected
        else:
            console.print(f"[yellow]Could not auto-detect platform for {url}[/yellow]")
            return

    job = {"url": url, "title": role, "company": company}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            if platform == "linkedin":
                from appliers.linkedin_applier import apply_linkedin_easy_apply
                creds = cfg.get("linkedin", {})
                # Log in first
                from scrapers.linkedin_scraper import login_linkedin
                await login_linkedin(page, creds["email"], creds["password"])
                result = await apply_linkedin_easy_apply(page, job, resume_path, cfg, dry_run)

            elif platform == "indeed":
                creds = cfg.get("indeed", {})
                await login_indeed(page, creds["email"], creds["password"])
                result = await apply_indeed_job(page, job, resume_path, cfg, dry_run)

            else:
                result = await apply_ats(page, job, resume_path, cover_letter, cfg, dry_run)

        finally:
            await browser.close()

    if result.get("success"):
        console.print(f"[green]Success:[/green] {company} — {role}")
        # Update sheet
        if not dry_run:
            _update_sheet_status(cfg, company, role, "Applied")
    else:
        console.print(f"[red]Failed:[/red] {result.get('message', 'Unknown error')}")


@cli.command()
@click.option("--platforms", default="indeed,linkedin", help="Comma-separated: indeed,linkedin")
@click.option("--config", default="~/job-apply-bot/config.yaml")
@click.option("--dry-run", is_flag=True, help="Scrape and tailor but don't submit applications")
@click.option("--max-apply", default=0, help="Override max daily applications (0 = use config)")
def run(platforms, config, dry_run, max_apply):
    """Full pipeline: scrape jobs → tailor resumes → auto-apply → log to Sheets."""
    cfg = load_config(config)
    asyncio.run(_run_pipeline(platforms.split(","), cfg, dry_run, max_apply))


async def _run_pipeline(platforms: list, cfg: dict, dry_run: bool, max_apply_override: int):
    from resume_tailor import extract_resume_text, tailor_resume, save_tailored_resume, generate_cover_letter
    from sheets_tracker import log_application, get_daily_stats

    resume_pdf = Path(cfg.get("resume", {}).get("base_pdf", "")).expanduser()
    if not resume_pdf.exists():
        console.print(f"[red]Resume not found: {resume_pdf}[/red]")
        return

    resume_text = extract_resume_text(str(resume_pdf))
    seen_urls = load_seen_urls()
    output_dir = cfg.get("resume", {}).get("output_dir", "~/job-apply/tailored")
    sheets_cfg = cfg.get("google_sheets", {})
    skip_cfg = cfg.get("skip_if", {})

    all_jobs = []

    # Scrape jobs from each platform
    if "linkedin" in platforms:
        console.print(Panel("[bold]Scraping LinkedIn...[/bold]", border_style="blue"))
        from scrapers.linkedin_scraper import scrape_linkedin
        linkedin_jobs = await scrape_linkedin(cfg, seen_urls)
        all_jobs.extend(linkedin_jobs)

    if "indeed" in platforms:
        console.print(Panel("[bold]Scraping Indeed...[/bold]", border_style="blue"))
        from scrapers.indeed_scraper import scrape_indeed
        indeed_jobs = await scrape_indeed(cfg, seen_urls)
        all_jobs.extend(indeed_jobs)

    save_seen_urls(seen_urls)
    console.print(f"\n[bold]Found {len(all_jobs)} new jobs to process[/bold]\n")

    applied_count = {"linkedin": 0, "indeed": 0, "ats": 0}
    rate_limits = cfg.get("rate_limits", {})

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        # Log in to platforms
        if "linkedin" in platforms:
            from scrapers.linkedin_scraper import login_linkedin
            await login_linkedin(page, cfg["linkedin"]["email"], cfg["linkedin"]["password"])

        if "indeed" in platforms:
            from appliers.indeed_applier import login_indeed
            await login_indeed(page, cfg["indeed"]["email"], cfg["indeed"]["password"])

        for job in all_jobs:
            platform = job.get("platform", "unknown")
            platform_limits = rate_limits.get(platform, rate_limits.get("greenhouse_lever_workday", {}))

            # Check daily limit
            daily_limit = max_apply_override or platform_limits.get("daily_apply_limit", 25)
            if applied_count.get(platform, 0) >= daily_limit:
                console.print(f"[yellow]Daily limit reached for {platform} ({daily_limit})[/yellow]")
                continue

            # Tailor resume
            console.print(f"\n[bold]Processing:[/bold] {job['company']} — {job['title']}")

            result = tailor_resume(resume_text, job.get("description", ""), job["company"], job["title"], cfg)
            scores = result.get("scores", {})
            overall_score = scores.get("overall", 5)

            # Skip if score too low
            if overall_score < skip_cfg.get("score_below", 0):
                console.print(f"[dim]Skipping (score {overall_score} < threshold)[/dim]")
                continue

            # Save tailored resume
            resume_file = save_tailored_resume(result["tailored_resume"], job["company"], job["title"], output_dir)
            cover_letter = generate_cover_letter(result.get("cover_letter_hook", ""), job["company"], job["title"], cfg)

            # Apply
            apply_result = {"success": False, "message": "Not attempted"}

            if not dry_run:
                from appliers.linkedin_applier import apply_linkedin_easy_apply
                from appliers.indeed_applier import apply_indeed_job
                from appliers.ats_applier import apply_ats, detect_ats

                if platform == "linkedin":
                    apply_result = await apply_linkedin_easy_apply(page, job, resume_file, cfg)
                elif platform == "indeed":
                    apply_result = await apply_indeed_job(page, job, resume_file, cfg)
                else:
                    ats = detect_ats(job["url"])
                    if ats:
                        apply_result = await apply_ats(page, job, resume_file, cover_letter, cfg)
            else:
                apply_result = {"success": True, "dry_run": True}

            status = "Applied" if apply_result.get("success") and not apply_result.get("dry_run") else (
                "Tailored" if apply_result.get("dry_run") else "Failed"
            )

            # Log to Sheets
            if sheets_cfg.get("spreadsheet_id"):
                log_application(
                    spreadsheet_id=sheets_cfg["spreadsheet_id"],
                    sheet_name=sheets_cfg.get("sheet_name", "Applications"),
                    credentials_file=sheets_cfg.get("credentials_file", ""),
                    company=job["company"],
                    role=job["title"],
                    location=job.get("location", ""),
                    platform=platform,
                    job_url=job.get("url", ""),
                    status=status,
                    scores=scores,
                    gaps=result.get("gaps", []),
                    ats_keywords=result.get("ats_keywords_added", []),
                    resume_file=resume_file,
                    cover_letter=cover_letter,
                )

            if apply_result.get("success"):
                applied_count[platform] = applied_count.get(platform, 0) + 1

            # Rate limit delay
            delay_range = platform_limits.get("delay_between_applies_sec", [30, 60])
            delay = random.uniform(*delay_range)
            console.print(f"[dim]Waiting {delay:.0f}s before next application...[/dim]")
            await asyncio.sleep(delay)

        await browser.close()

    # Summary
    total = sum(applied_count.values())
    console.print(Panel(
        f"[bold green]Run Complete[/bold green]\n"
        f"Total jobs found: {len(all_jobs)}\n"
        f"Applications submitted: {total}\n"
        f"  LinkedIn: {applied_count.get('linkedin', 0)}\n"
        f"  Indeed:   {applied_count.get('indeed', 0)}\n"
        f"  ATS:      {applied_count.get('ats', 0)}\n"
        f"{'[yellow]DRY RUN — no applications submitted[/yellow]' if dry_run else ''}",
        title="Summary"
    ))


@cli.command()
@click.option("--company", required=True)
@click.option("--role", required=True)
@click.option("--location", default="")
@click.option("--url", default="")
@click.option("--score", default=0, type=int)
@click.option("--status", default="Applied")
@click.option("--resume-file", default="")
@click.option("--config", default="~/job-apply-bot/config.yaml")
def log(company, role, location, url, score, status, resume_file, config):
    """Manually log a job application to Google Sheets."""
    cfg = load_config(config)
    sheets_cfg = cfg.get("google_sheets", {})

    if not sheets_cfg.get("spreadsheet_id"):
        console.print("[red]No Google Sheets configured in config.yaml[/red]")
        return

    from sheets_tracker import log_application
    log_application(
        spreadsheet_id=sheets_cfg["spreadsheet_id"],
        sheet_name=sheets_cfg.get("sheet_name", "Applications"),
        credentials_file=sheets_cfg.get("credentials_file", ""),
        company=company,
        role=role,
        location=location,
        platform="manual",
        job_url=url,
        status=status,
        scores={"overall": score} if score else None,
        resume_file=resume_file,
    )


@cli.command()
@click.option("--config", default="~/job-apply-bot/config.yaml")
def stats(config):
    """Show today's application statistics from Google Sheets."""
    cfg = load_config(config)
    sheets_cfg = cfg.get("google_sheets", {})

    if not sheets_cfg.get("spreadsheet_id"):
        console.print("[yellow]No Google Sheets configured[/yellow]")
        return

    from sheets_tracker import get_daily_stats
    s = get_daily_stats(
        spreadsheet_id=sheets_cfg["spreadsheet_id"],
        sheet_name=sheets_cfg.get("sheet_name", "Applications"),
        credentials_file=sheets_cfg.get("credentials_file", ""),
    )

    table = Table(title=f"Application Stats — Today")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="green", justify="right")

    table.add_row("Today's Applications", str(s["today_total"]))
    table.add_row("All-Time Total", str(s["total_all_time"]))
    table.add_section()

    for field, count in s.get("by_field", {}).items():
        table.add_row(f"  {field}", str(count))
    table.add_section()

    for status, count in s["by_status"].items():
        table.add_row(f"  {status}", str(count))

    console.print(table)


@cli.command()
@click.option("--row", default=0, type=int, help="Row number to prep (2 = first data row). Defaults to first 'To Apply' row.")
@click.option("--config", default="~/job-apply-bot/config.yaml")
def prep_row(row, config):
    """Scrape a job from the sheet and print everything Claude needs to tailor the resume."""
    cfg = load_config(config)
    sheets_cfg = cfg.get("google_sheets", {})

    from pathlib import Path as _Path
    creds_file = str(_Path(sheets_cfg.get("credentials_file", "")).expanduser())
    from sheets_tracker import get_row, get_first_row_by_status

    # ── 1. Get row ───────────────────────────────────────────────────────────
    if row >= 2:
        row_data = get_row(sheets_cfg["spreadsheet_id"], sheets_cfg.get("sheet_name", "Applications"), creds_file, row)
        row_number = row
    else:
        row_number, row_data = get_first_row_by_status(
            sheets_cfg["spreadsheet_id"], sheets_cfg.get("sheet_name", "Applications"),
            creds_file, status="To Apply"
        )

    if not row_data:
        console.print("[red]Row not found.[/red]")
        return

    company     = row_data.get("Company", "")
    role_title  = row_data.get("Role", "")
    location    = row_data.get("Location", "")
    field_label = row_data.get("Field", "")
    job_url     = row_data.get("Apply Link", "")

    # ── 2. Scrape JD ─────────────────────────────────────────────────────────
    from src.job_scraper import scrape_job_description
    job_desc = scrape_job_description(job_url) or ""

    if not job_desc:
        console.print("[yellow]Could not scrape — paste the job description below (Ctrl+D when done):[/yellow]")
        lines = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            pass
        job_desc = "\n".join(lines)

    # ── 3. Load base resume from Google Doc ──────────────────────────────────
    gdocs_cfg   = cfg.get("google_docs", {})
    base_doc_id = gdocs_cfg.get("single_base_doc_id", "")
    creds_file  = str(_Path(sheets_cfg.get("credentials_file", "")).expanduser())

    if base_doc_id:
        from src.gdocs import read_doc_text
        resume_text, _ = read_doc_text(base_doc_id, creds_file)
        console.print("[dim]Loaded base resume from Google Doc[/dim]")
    else:
        # Fallback: use the software_eng .md file
        from src.field_classifier import get_base_resume_path
        base_path = _Path(__file__).parent / get_base_resume_path("software_eng")
        resume_text = base_path.read_text() if base_path.exists() else ""

    # ── 4. Print context block for Claude ────────────────────────────────────
    from resume_tailor import prep_for_claude
    prompt = prep_for_claude(resume_text, job_desc, company, role_title)

    console.print(Panel(
        f"Row {row_number} | [bold]{company}[/bold] — {role_title}\n"
        f"Field: {field_label} | Location: {location}",
        title="Ready to tailor"
    ))
    console.print("\n[bold yellow]── PASTE THIS INTO CLAUDE CODE ──[/bold yellow]\n")
    print(prompt)
    console.print(f"\n[bold yellow]── END ──[/bold yellow]")
    console.print(f"\n[dim]After Claude responds, run:[/dim]")
    console.print(f"  python3 main.py save-tailored --row {row_number} --company \"{company}\" --role \"{role_title}\"")


@cli.command()
@click.option("--row",     required=True, type=int, help="Sheet row number to update")
@click.option("--company", required=True, help="Company name (for filename)")
@click.option("--role",    required=True, help="Role title (for filename)")
@click.option("--config",  default="~/job-apply-bot/config.yaml")
def save_tailored(row, company, role, config):
    """Paste Claude's JSON response → saves resume .md + creates Google Doc + updates sheet row."""
    cfg = load_config(config)
    sheets_cfg = cfg.get("google_sheets", {})

    from pathlib import Path as _Path
    creds_file = str(_Path(sheets_cfg.get("credentials_file", "")).expanduser())

    console.print("[yellow]Paste Claude's JSON response then Ctrl+D:[/yellow]")
    lines = []
    try:
        while True:
            lines.append(input())
    except EOFError:
        pass
    raw = "\n".join(lines).strip()

    import json, re as _re
    # Strip markdown fences if present
    raw = _re.sub(r'^```(?:json)?\s*', '', raw)
    raw = _re.sub(r'\s*```$', '', raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        console.print(f"[red]Could not parse JSON: {e}[/red]")
        console.print("[dim]Make sure you copied Claude's full JSON response.[/dim]")
        return

    tailored_text = result.get("tailored_resume", "")
    scores        = result.get("scores", {})
    gaps          = result.get("gaps", [])
    ats_keywords  = result.get("ats_keywords_added", [])

    if not tailored_text:
        console.print("[red]No 'tailored_resume' key found in JSON.[/red]")
        return

    # ── Save local .md file ──────────────────────────────────────────────────
    from resume_tailor import save_tailored_resume
    output_dir  = cfg.get("resume", {}).get("output_dir", "resumes/tailored")
    resume_file = save_tailored_resume(tailored_text, company, role, output_dir)
    resume_filename = _Path(resume_file).name

    # ── Create tailored Google Doc ────────────────────────────────────────────
    resume_ref = resume_filename  # fallback: just store filename
    gdocs_cfg  = cfg.get("google_docs", {})
    base_doc_id = gdocs_cfg.get("single_base_doc_id", "")
    if base_doc_id:
        try:
            from src.gdocs import apply_tailoring_to_doc
            doc_url = apply_tailoring_to_doc(
                base_doc_id=base_doc_id,
                tailored_md=tailored_text,
                company=company,
                role=role,
                credentials_file=creds_file,
                root_folder_id=gdocs_cfg.get("root_folder_id") or None,
            )
            resume_ref = f'=HYPERLINK("{doc_url}","View Resume")'
        except Exception as e:
            console.print(f"[yellow]Google Doc creation failed (storing filename instead): {e}[/yellow]")

    # ── Update sheet ─────────────────────────────────────────────────────────
    from sheets_tracker import update_row_after_tailor
    update_row_after_tailor(
        spreadsheet_id=sheets_cfg["spreadsheet_id"],
        sheet_name=sheets_cfg.get("sheet_name", "Applications"),
        credentials_file=creds_file,
        row_number=row,
        scores=scores,
        gaps=gaps,
        ats_keywords=ats_keywords,
        resume_file=resume_ref,
        status="Tailored",
    )

    # ── Print score table ─────────────────────────────────────────────────────
    table = Table(title=f"{company} — Match Scores")
    table.add_column("Metric", style="cyan")
    table.add_column("Score",  style="green")
    table.add_row("Skills Match",     f"{scores.get('skills_match', '?')}/10")
    table.add_row("Experience Match", f"{scores.get('experience_match', '?')}/10")
    table.add_row("Industry Match",   f"{scores.get('industry_match', '?')}/10")
    table.add_row("Overall",          f"[bold]{scores.get('overall', '?')}/10[/bold]")
    console.print(table)

    if gaps:
        console.print(f"[yellow]Gaps:[/yellow] {', '.join(gaps)}")

    doc_line = f"[bold]Doc:[/bold]   {resume_ref}\n" if "HYPERLINK" in resume_ref else f"[bold]File:[/bold]  {resume_file}\n"
    console.print(Panel(
        f"[bold green]Done![/bold green]\n\n"
        f"{doc_line}"
        f"[bold]Score:[/bold] {scores.get('overall', '?')}/10\n\n"
        f"[dim]Open the sheet → click Apply → change Status to 'Applied'.[/dim]",
        title=f"{company} — {role}"
    ))


@cli.command()
@click.option("--email",  default="", help="Your Google account email to share the folder with")
@click.option("--config", default="~/job-apply-bot/config.yaml")
def setup_gdocs(email, config):
    """Create Drive folder + 4 base template Google Docs, then save IDs to config."""
    cfg = load_config(config)
    sheets_cfg = cfg.get("google_sheets", {})
    creds_file = str(Path(sheets_cfg.get("credentials_file", "")).expanduser())

    user_email = email or cfg.get("personal", {}).get("email", "") or cfg.get("google_docs", {}).get("user_email", "")

    console.print("[bold]Setting up Google Drive folder and base template docs...[/bold]")

    from src.gdocs import setup_base_docs
    doc_ids, root_folder_id = setup_base_docs(
        credentials_file=creds_file,
        user_email=user_email or None,
    )

    # Persist IDs back into config.yaml
    config_path = Path(config).expanduser()
    with open(config_path) as f:
        cfg_data = yaml.safe_load(f)

    if "google_docs" not in cfg_data:
        cfg_data["google_docs"] = {}
    cfg_data["google_docs"]["root_folder_id"] = root_folder_id
    cfg_data["google_docs"]["base_doc_ids"]   = doc_ids
    if user_email:
        cfg_data["google_docs"]["user_email"] = user_email

    with open(config_path, "w") as f:
        yaml.dump(cfg_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    console.print(f"\n[bold green]Config updated:[/bold green] {config_path}")
    console.print(f"[dim]root_folder_id: {root_folder_id}[/dim]")
    for k, v in doc_ids.items():
        console.print(f"[dim]  {k}: {v}[/dim]")


def _update_sheet_status(cfg: dict, company: str, role: str, status: str):
    sheets_cfg = cfg.get("google_sheets", {})
    if not sheets_cfg.get("spreadsheet_id"):
        return
    from sheets_tracker import update_status
    update_status(
        spreadsheet_id=sheets_cfg["spreadsheet_id"],
        sheet_name=sheets_cfg.get("sheet_name", "Applications"),
        credentials_file=sheets_cfg.get("credentials_file", ""),
        company=company,
        role=role,
        new_status=status,
    )


if __name__ == "__main__":
    cli()
