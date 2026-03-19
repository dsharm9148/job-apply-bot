"""
ATS applier for Greenhouse, Lever, and Workday.
Detects which ATS a job is hosted on and uses the appropriate flow.
"""

import asyncio
import random
import re
from pathlib import Path

from playwright.async_api import Page
from rich.console import Console

console = Console()


def detect_ats(url: str) -> str | None:
    """Detect which ATS is being used from the URL."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower or "boards.greenhouse.io" in url_lower:
        return "greenhouse"
    elif "lever.co" in url_lower or "jobs.lever.co" in url_lower:
        return "lever"
    elif "myworkdayjobs.com" in url_lower or "workday.com" in url_lower:
        return "workday"
    elif "taleo.net" in url_lower:
        return "taleo"
    elif "icims.com" in url_lower:
        return "icims"
    elif "smartrecruiters.com" in url_lower:
        return "smartrecruiters"
    return None


async def _human_delay(min_sec: float = 0.8, max_sec: float = 3.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def apply_ats(
    page: Page,
    job: dict,
    resume_path: str,
    cover_letter: str,
    config: dict,
    dry_run: bool = False,
) -> dict:
    """Apply via ATS. Auto-detects Greenhouse/Lever/Workday."""
    ats = detect_ats(job["url"])

    if not ats:
        return {"success": False, "skipped": True, "message": "Unknown ATS"}

    console.print(f"[blue]Applying via {ats.title()}:[/blue] {job['company']} — {job['title']}")

    if dry_run:
        return {"success": True, "dry_run": True, "message": f"Would apply via {ats}"}

    handlers = {
        "greenhouse": _apply_greenhouse,
        "lever": _apply_lever,
        "workday": _apply_workday,
        "smartrecruiters": _apply_smartrecruiters,
    }

    handler = handlers.get(ats)
    if handler:
        return await handler(page, job, resume_path, cover_letter, config)

    return {"success": False, "message": f"No handler for {ats}"}


# ─── GREENHOUSE ──────────────────────────────────────────────────────────────

async def _apply_greenhouse(page, job, resume_path, cover_letter, config):
    """Apply via Greenhouse ATS."""
    personal = config.get("personal", {})

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    # Find Apply button if on job listing page
    apply_btn = await page.query_selector('#apply_button, a[href*="applications/new"], button:has-text("Apply")')
    if apply_btn:
        await apply_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(1.5, 3)

    # Fill standard Greenhouse fields
    gh_fields = {
        '#first_name': personal.get("full_name", "").split(" ")[0],
        '#last_name': " ".join(personal.get("full_name", "").split(" ")[1:]),
        '#email': personal.get("email", ""),
        '#phone': personal.get("phone", ""),
        'input[name="job_application[location]"]': personal.get("location", ""),
        '#job_application_cover_letter': cover_letter,
    }

    for selector, value in gh_fields.items():
        if not value:
            continue
        try:
            el = await page.query_selector(selector)
            if el:
                await el.fill(value)
                await _human_delay(0.3, 0.8)
        except Exception:
            continue

    # Resume upload
    resume_input = await page.query_selector('input[type="file"][name*="resume"], input[id*="resume"]')
    if resume_input:
        await resume_input.set_input_files(str(Path(resume_path).expanduser().resolve()))
        await _human_delay(1.5, 3)

    # Handle custom questions
    await _fill_greenhouse_custom_questions(page, config)

    # Submit
    submit_btn = await page.query_selector('#submit_app, button[type="submit"], input[type="submit"][value*="Submit"]')
    if submit_btn:
        await submit_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(2, 4)
        console.print(f"[green]Applied (Greenhouse):[/green] {job['company']}")
        return {"success": True, "message": "Applied via Greenhouse"}

    return {"success": False, "message": "Could not find submit button"}


async def _fill_greenhouse_custom_questions(page: Page, config: dict):
    """Fill Greenhouse custom application questions."""
    answers = config.get("form_answers", {})

    # Yes/No selects (common in Greenhouse)
    selects = await page.query_selector_all('select[id*="question"]')
    for sel in selects:
        label_id = await sel.get_attribute("aria-labelledby") or ""

        # Try to find associated label
        label_text = ""
        if label_id:
            label_el = await page.query_selector(f'#{label_id}')
            if label_el:
                label_text = (await label_el.inner_text()).lower()

        if "authorized" in label_text:
            await sel.select_option(value="1")  # Yes
        elif "sponsor" in label_text:
            need = answers.get("require_sponsorship", False)
            await sel.select_option(value="1" if need else "0")

        await _human_delay(0.2, 0.5)


# ─── LEVER ────────────────────────────────────────────────────────────────────

async def _apply_lever(page, job, resume_path, cover_letter, config):
    """Apply via Lever ATS."""
    personal = config.get("personal", {})

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    # Lever application form fields
    lever_fields = {
        'input[name="name"]': personal.get("full_name", ""),
        'input[name="email"]': personal.get("email", ""),
        'input[name="phone"]': personal.get("phone", ""),
        'input[name="org"]': "",  # current company, optional
        'input[name="urls[LinkedIn]"]': personal.get("linkedin_url", ""),
        'input[name="urls[GitHub]"]': personal.get("github_url", ""),
        'input[name="urls[Portfolio]"]': personal.get("portfolio_url", ""),
        'textarea[name="comments"]': cover_letter[:2000] if cover_letter else "",
    }

    for selector, value in lever_fields.items():
        if not value:
            continue
        try:
            el = await page.query_selector(selector)
            if el:
                await el.fill(value)
                await _human_delay(0.3, 0.8)
        except Exception:
            continue

    # Resume upload
    file_inputs = await page.query_selector_all('input[type="file"]')
    if file_inputs:
        await file_inputs[0].set_input_files(str(Path(resume_path).expanduser().resolve()))
        await _human_delay(1.5, 3)

    # Submit
    submit_btn = await page.query_selector('button[type="submit"], input[type="submit"]')
    if submit_btn:
        await submit_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(2, 4)
        console.print(f"[green]Applied (Lever):[/green] {job['company']}")
        return {"success": True, "message": "Applied via Lever"}

    return {"success": False, "message": "Could not find submit button"}


# ─── WORKDAY ──────────────────────────────────────────────────────────────────

async def _apply_workday(page, job, resume_path, cover_letter, config):
    """
    Apply via Workday ATS.
    Workday is complex — handles the most common flow.
    """
    personal = config.get("personal", {})

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(3, 6)

    # Find Apply button
    apply_btn = await page.query_selector(
        'a[data-automation-id*="apply"], button[data-automation-id*="apply"], '
        'button:has-text("Apply"), a:has-text("Apply Now")'
    )
    if apply_btn:
        await apply_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(3, 5)

    # Workday may ask to create account / sign in
    create_acct = await page.query_selector('button:has-text("Create Account"), a:has-text("Create Account")')
    if create_acct:
        console.print("[yellow]Workday requires account creation — manual step needed[/yellow]")
        console.print(f"Please create an account and log in, then press Enter...")
        input()

    # Upload resume (Workday parses resume to fill fields)
    file_input = await page.query_selector('input[type="file"]')
    if file_input:
        await file_input.set_input_files(str(Path(resume_path).expanduser().resolve()))
        await _human_delay(3, 6)  # Workday takes time to parse

    # Fill fields Workday didn't auto-populate from resume
    await _fill_workday_fields(page, personal)

    # Navigate through Workday's multi-step form
    max_steps = 15
    for _ in range(max_steps):
        await _human_delay(1.5, 3)

        submit_btn = await page.query_selector(
            'button[data-automation-id="bottom-navigation-next-button"]:has-text("Submit"), '
            'button:has-text("Submit")'
        )
        next_btn = await page.query_selector(
            'button[data-automation-id="bottom-navigation-next-button"]'
        )

        if submit_btn:
            await submit_btn.click()
            await page.wait_for_load_state("networkidle")
            await _human_delay(2, 4)
            console.print(f"[green]Applied (Workday):[/green] {job['company']}")
            return {"success": True, "message": "Applied via Workday"}
        elif next_btn:
            await next_btn.click()
            await page.wait_for_load_state("networkidle")
        else:
            break

    return {"success": False, "message": "Workday form navigation incomplete"}


async def _fill_workday_fields(page: Page, personal: dict):
    """Fill Workday form fields."""
    workday_fields = {
        'input[data-automation-id*="legalName-firstName"]': personal.get("full_name", "").split(" ")[0],
        'input[data-automation-id*="legalName-lastName"]': " ".join(personal.get("full_name", "").split(" ")[1:]),
        'input[data-automation-id*="email"]': personal.get("email", ""),
        'input[data-automation-id*="phone"]': personal.get("phone", ""),
    }

    for selector, value in workday_fields.items():
        if not value:
            continue
        try:
            el = await page.query_selector(selector)
            if el:
                current = await el.input_value()
                if not current:
                    await el.fill(value)
                    await _human_delay(0.3, 0.7)
        except Exception:
            continue


# ─── SMARTRECRUITERS ─────────────────────────────────────────────────────────

async def _apply_smartrecruiters(page, job, resume_path, cover_letter, config):
    """Apply via SmartRecruiters ATS."""
    personal = config.get("personal", {})

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    apply_btn = await page.query_selector('a[href*="/apply"], button:has-text("Apply")')
    if apply_btn:
        await apply_btn.click()
        await page.wait_for_load_state("networkidle")
        await _human_delay(2, 3)

    sr_fields = {
        'input[id*="firstName"]': personal.get("full_name", "").split(" ")[0],
        'input[id*="lastName"]': " ".join(personal.get("full_name", "").split(" ")[1:]),
        'input[id*="email"]': personal.get("email", ""),
        'input[id*="phone"]': personal.get("phone", ""),
    }

    for selector, value in sr_fields.items():
        if not value:
            continue
        try:
            el = await page.query_selector(selector)
            if el:
                await el.fill(value)
                await _human_delay(0.3, 0.7)
        except Exception:
            continue

    file_input = await page.query_selector('input[type="file"]')
    if file_input:
        await file_input.set_input_files(str(Path(resume_path).expanduser().resolve()))
        await _human_delay(2, 4)

    submit_btn = await page.query_selector('button[type="submit"]')
    if submit_btn:
        await submit_btn.click()
        await page.wait_for_load_state("networkidle")
        console.print(f"[green]Applied (SmartRecruiters):[/green] {job['company']}")
        return {"success": True, "message": "Applied via SmartRecruiters"}

    return {"success": False, "message": "Could not submit"}
