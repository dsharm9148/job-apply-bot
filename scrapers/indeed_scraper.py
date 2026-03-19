"""
Indeed job scraper using Playwright.
More automation-friendly than LinkedIn.
"""

import asyncio
import random
import re
from datetime import datetime
from urllib.parse import quote_plus
from typing import Optional

from playwright.async_api import async_playwright, Page
from rich.console import Console

console = Console()


async def _human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def _type_like_human(page: Page, selector: str, text: str):
    await page.click(selector)
    await _human_delay(0.2, 0.6)
    await page.fill(selector, "")
    for char in text:
        await page.keyboard.type(char)
        await asyncio.sleep(random.uniform(0.04, 0.15))


async def search_indeed_jobs(
    page: Page,
    job_title: str,
    location: str,
    max_results: int = 50,
    remote_only: bool = False,
) -> list[dict]:
    """Search Indeed for jobs and return list of job dicts."""
    jobs = []
    start = 0
    page_size = 15  # Indeed shows ~15 results per page

    while len(jobs) < max_results:
        query = quote_plus(job_title)
        loc = quote_plus(location)
        remoteness = "&remotejob=032b3046-06a3-4876-8dfd-474eb5e7ed11" if remote_only else ""
        url = f"https://www.indeed.com/jobs?q={query}&l={loc}&start={start}{remoteness}"

        console.print(f"[dim]Indeed page {start // page_size + 1}: {job_title}[/dim]")
        await page.goto(url)
        await page.wait_for_load_state("networkidle")
        await _human_delay(2, 4)

        # Handle "Are you a robot?" / CAPTCHA
        if "captcha" in page.url.lower() or "sorry" in await page.title():
            console.print("[yellow]CAPTCHA detected on Indeed. Waiting for manual solve...[/yellow]")
            input("Solve the CAPTCHA then press Enter...")

        job_cards = await page.query_selector_all('[data-jk], .job_seen_beacon, .tapItem')

        if not job_cards:
            console.print("[dim]No more results[/dim]")
            break

        for card in job_cards:
            if len(jobs) >= max_results:
                break
            job = await _extract_indeed_card(page, card)
            if job:
                jobs.append(job)

        await _human_delay(1, 3)
        start += page_size

        # Check for next page
        next_btn = await page.query_selector('[aria-label="Next Page"], [data-testid="pagination-page-next"]')
        if not next_btn:
            break

    console.print(f"[green]Found {len(jobs)} Indeed jobs[/green]")
    return jobs


async def _extract_indeed_card(page: Page, card) -> dict | None:
    """Extract job info from an Indeed job card."""
    try:
        # Get job key for URL
        job_key = await card.get_attribute("data-jk") or ""

        title_el = await card.query_selector('[class*="jobTitle"] a, h2.jobTitle a, .title a')
        company_el = await card.query_selector('[data-testid="company-name"], .companyName, [class*="companyName"]')
        location_el = await card.query_selector('[data-testid="text-location"], .companyLocation, [class*="companyLocation"]')
        salary_el = await card.query_selector('[class*="salary"], [data-testid="attribute_snippet_testid"]')
        snippet_el = await card.query_selector('.job-snippet, [class*="snippet"]')

        if not title_el:
            return None

        title = await title_el.inner_text()
        company = await company_el.inner_text() if company_el else ""
        location = await location_el.inner_text() if location_el else ""
        salary = await salary_el.inner_text() if salary_el else ""
        snippet = await snippet_el.inner_text() if snippet_el else ""

        job_url = f"https://www.indeed.com/viewjob?jk={job_key}" if job_key else ""

        # Click to get full description
        description = snippet
        if title_el:
            try:
                await title_el.click()
                await _human_delay(1.5, 3)

                desc_el = await page.wait_for_selector(
                    '#jobDescriptionText, .jobsearch-JobComponent-description, [class*="jobDescription"]',
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
            "salary": salary.strip(),
            "url": job_url,
            "description": description.strip()[:5000],
            "easy_apply": True,  # Indeed's "Apply Now" is generally direct
            "platform": "indeed",
            "scraped_at": datetime.now().isoformat(),
        }
    except Exception as e:
        console.print(f"[dim]Card parse error: {e}[/dim]")
        return None


async def scrape_indeed(config: dict, seen_urls: set = None) -> list[dict]:
    """Main entry: scrape Indeed jobs per config."""
    seen_urls = seen_urls or set()
    rate_limits = config.get("rate_limits", {}).get("indeed", {})
    daily_limit = rate_limits.get("daily_scrape_limit", 500)

    search_config = config.get("search", {})
    job_titles = search_config.get("job_titles", [])
    locations = search_config.get("locations", ["Remote"])
    excluded = [c.lower() for c in search_config.get("excluded_companies", [])]

    all_jobs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            per_title = max(1, daily_limit // max(len(job_titles), 1))

            for title in job_titles:
                for location in locations:
                    remote_only = location.lower() == "remote"
                    loc = "" if remote_only else location

                    console.print(f"[blue]Scraping Indeed:[/blue] {title} @ {location}")
                    jobs = await search_indeed_jobs(
                        page, title, loc,
                        max_results=per_title,
                        remote_only=remote_only,
                    )

                    for job in jobs:
                        if job["url"] in seen_urls:
                            continue
                        if any(exc in job["company"].lower() for exc in excluded):
                            continue
                        all_jobs.append(job)
                        seen_urls.add(job["url"])

                    await _human_delay(3, 8)
        finally:
            await browser.close()

    console.print(f"[green]Indeed scrape complete:[/green] {len(all_jobs)} new jobs")
    return all_jobs[:daily_limit]
