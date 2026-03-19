"""
LinkedIn job scraper using Playwright.
Searches for jobs matching configured criteria and returns job listings.

WARNING: LinkedIn ToS prohibits automated scraping. Use responsibly.
Apply rate limits and human-like behavior to avoid account suspension.
"""

import asyncio
import random
import json
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from playwright.async_api import async_playwright, Page, Browser
from rich.console import Console

console = Console()


async def _human_delay(min_sec: float = 1.0, max_sec: float = 3.5):
    """Random delay to simulate human behavior."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def _type_like_human(page: Page, selector: str, text: str):
    """Type text with random delays between keystrokes."""
    await page.click(selector)
    await _human_delay(0.3, 0.8)
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.05, 0.2))


async def login_linkedin(page: Page, email: str, password: str):
    """Log in to LinkedIn."""
    console.print("[dim]Logging in to LinkedIn...[/dim]")
    await page.goto("https://www.linkedin.com/login")
    await _human_delay(1, 2)

    await _type_like_human(page, "#username", email)
    await _human_delay(0.5, 1)
    await _type_like_human(page, "#password", password)
    await _human_delay(0.5, 1)

    await page.click('[type="submit"]')
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    if "checkpoint" in page.url or "verify" in page.url:
        console.print("[yellow]LinkedIn is asking for verification. Please complete it manually.[/yellow]")
        console.print("Press Enter when done...")
        input()

    console.print("[green]Logged in to LinkedIn[/green]")


async def search_linkedin_jobs(
    page: Page,
    job_title: str,
    location: str,
    easy_apply_only: bool = True,
    max_results: int = 50,
    experience_levels: list = None,
) -> list[dict]:
    """
    Search LinkedIn for jobs and return list of job dicts.
    Each dict has: title, company, location, url, description, easy_apply
    """
    jobs = []

    # Build search URL
    params = {
        "keywords": job_title,
        "location": location,
        "f_AL": "true" if easy_apply_only else "",  # Easy Apply filter
    }

    if experience_levels:
        level_map = {"entry": "1", "mid": "2", "senior": "3", "director": "4"}
        level_codes = ",".join(level_map[l] for l in experience_levels if l in level_map)
        if level_codes:
            params["f_E"] = level_codes

    query = "&".join(f"{k}={v}" for k, v in params.items() if v)
    url = f"https://www.linkedin.com/jobs/search/?{query}"

    console.print(f"[dim]Searching LinkedIn: {job_title} in {location}[/dim]")
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    page_num = 0
    while len(jobs) < max_results:
        # Scroll to load all job cards
        for _ in range(5):
            await page.keyboard.press("End")
            await _human_delay(0.5, 1.5)

        # Get all job cards on this page
        job_cards = await page.query_selector_all(".job-card-container, .jobs-search-results__list-item")

        for card in job_cards:
            if len(jobs) >= max_results:
                break
            try:
                job = await _extract_linkedin_card(page, card)
                if job:
                    jobs.append(job)
                    await _human_delay(0.2, 0.8)
            except Exception as e:
                console.print(f"[dim]Card parse error: {e}[/dim]")
                continue

        # Try next page
        next_btn = await page.query_selector('[aria-label="Next"]')
        if not next_btn or len(jobs) >= max_results:
            break

        await next_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(3, 7)
        page_num += 1

    console.print(f"[green]Found {len(jobs)} LinkedIn jobs[/green]")
    return jobs


async def _extract_linkedin_card(page: Page, card) -> dict | None:
    """Extract job info from a LinkedIn job card."""
    try:
        title_el = await card.query_selector(".job-card-list__title, .job-card-container__link")
        company_el = await card.query_selector(".job-card-container__primary-description, .artdeco-entity-lockup__subtitle")
        location_el = await card.query_selector(".job-card-container__metadata-item")
        easy_apply_el = await card.query_selector(".job-card-container__apply-method")
        link_el = await card.query_selector("a.job-card-list__title, a.job-card-container__link")

        if not title_el:
            return None

        title = await title_el.inner_text()
        company = await company_el.inner_text() if company_el else ""
        location = await location_el.inner_text() if location_el else ""
        easy_apply_text = await easy_apply_el.inner_text() if easy_apply_el else ""
        href = await link_el.get_attribute("href") if link_el else ""

        job_url = f"https://www.linkedin.com{href}" if href.startswith("/") else href

        # Get job description by clicking the card
        await card.click()
        await _human_delay(1, 2.5)

        description = ""
        try:
            desc_el = await page.wait_for_selector(
                ".jobs-description__content, .job-view-layout",
                timeout=5000
            )
            if desc_el:
                description = await desc_el.inner_text()
        except Exception:
            pass

        return {
            "title": title.strip(),
            "company": company.strip(),
            "location": location.strip(),
            "url": job_url,
            "description": description.strip()[:5000],  # cap length
            "easy_apply": "easy apply" in easy_apply_text.lower(),
            "platform": "linkedin",
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception:
        return None


async def scrape_linkedin(config: dict, seen_urls: set = None) -> list[dict]:
    """
    Main entry point: scrape LinkedIn jobs per config.
    Returns list of new (unseen) job dicts.
    """
    seen_urls = seen_urls or set()
    rate_limits = config.get("rate_limits", {}).get("linkedin", {})
    daily_limit = rate_limits.get("daily_scrape_limit", 200)

    search_config = config.get("search", {})
    job_titles = search_config.get("job_titles", [])
    locations = search_config.get("locations", ["Remote"])
    experience_levels = search_config.get("experience_levels", [])
    excluded = [c.lower() for c in search_config.get("excluded_companies", [])]

    linkedin_creds = config.get("linkedin", {})

    all_jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # visible browser for LinkedIn (less detectable)
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()

        # Remove webdriver flag
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            await login_linkedin(page, linkedin_creds["email"], linkedin_creds["password"])

            per_title = max(1, daily_limit // max(len(job_titles), 1))

            for title in job_titles:
                for location in locations:
                    console.print(f"[blue]Scraping:[/blue] {title} @ {location}")
                    jobs = await search_linkedin_jobs(
                        page, title, location,
                        easy_apply_only=True,
                        max_results=per_title,
                        experience_levels=experience_levels,
                    )

                    for job in jobs:
                        # Filter
                        if job["url"] in seen_urls:
                            continue
                        if any(exc in job["company"].lower() for exc in excluded):
                            continue
                        all_jobs.append(job)
                        seen_urls.add(job["url"])

                    await _human_delay(5, 15)  # break between searches

        finally:
            await browser.close()

    console.print(f"[green]LinkedIn scrape complete:[/green] {len(all_jobs)} new jobs")
    return all_jobs[:daily_limit]
