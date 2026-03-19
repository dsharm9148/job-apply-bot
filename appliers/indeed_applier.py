"""
Indeed job applier using Playwright.
Handles Indeed's "Apply Now" flow and Indeedresume-based applications.
"""

import asyncio
import random
from pathlib import Path

from playwright.async_api import Page
from rich.console import Console

console = Console()


async def _human_delay(min_sec: float = 0.8, max_sec: float = 2.5):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def login_indeed(page: Page, email: str, password: str):
    """Log in to Indeed."""
    await page.goto("https://secure.indeed.com/auth?hl=en_US&co=US&continue=%2F&tmpl=desktop&service=my&from=gnav-homepage")
    await page.wait_for_load_state("networkidle")
    await _human_delay(1.5, 3)

    # Enter email
    email_field = await page.query_selector('input[name="__email"], input[type="email"]')
    if email_field:
        await email_field.fill(email)
        await _human_delay(0.5, 1)

    continue_btn = await page.query_selector('button[type="submit"]')
    if continue_btn:
        await continue_btn.click()
        await _human_delay(1.5, 3)

    # Enter password
    pass_field = await page.query_selector('input[name="__password"], input[type="password"]')
    if pass_field:
        await pass_field.fill(password)
        await _human_delay(0.5, 1)
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
        await _human_delay(2, 4)

    console.print("[green]Logged in to Indeed[/green]")


async def apply_indeed_job(
    page: Page,
    job: dict,
    resume_path: str,
    config: dict,
    dry_run: bool = False,
) -> dict:
    """Apply to a single Indeed job. Returns result dict."""
    personal = config.get("personal", {})
    answers = config.get("form_answers", {})

    console.print(f"[blue]Applying (Indeed):[/blue] {job['company']} — {job['title']}")

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    if dry_run:
        console.print(f"[yellow][DRY RUN] Would apply to {job['company']}[/yellow]")
        return {"success": True, "dry_run": True}

    # Find Apply button
    apply_btn = await page.query_selector(
        'button[id*="apply"], a[id*="apply"], '
        '[class*="apply-button"], [data-testid*="apply"]'
    )

    if not apply_btn:
        return {"success": False, "skipped": True, "message": "No apply button found"}

    await apply_btn.click()
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    # May open in new tab or redirect
    pages = page.context.pages
    apply_page = pages[-1] if len(pages) > 1 else page

    # Handle multi-page Indeed application
    max_steps = 8
    for step in range(max_steps):
        current_url = apply_page.url

        # Resume upload
        upload_input = await apply_page.query_selector('input[type="file"]')
        if upload_input:
            resume_abs = str(Path(resume_path).expanduser().resolve())
            await upload_input.set_input_files(resume_abs)
            await _human_delay(1, 2)

        # Fill standard text fields
        await _fill_indeed_fields(apply_page, personal, answers)

        # Yes/No questions
        await _handle_indeed_questions(apply_page, answers)

        # Submit or continue
        submit_btn = await apply_page.query_selector(
            'button[type="submit"][id*="submit"], '
            'button:has-text("Submit your application"), '
            'button:has-text("Submit application")'
        )
        continue_btn = await apply_page.query_selector(
            'button[type="submit"]:not([id*="submit"]), '
            'button:has-text("Continue"), '
            'button:has-text("Next")'
        )

        if submit_btn:
            await submit_btn.click()
            await _human_delay(2, 4)

            # Check for success
            success_indicator = await apply_page.query_selector(
                '[class*="success"], [class*="confirmation"], '
                'h1:has-text("application"), h2:has-text("applied")'
            )
            console.print(f"[green]Applied (Indeed):[/green] {job['company']} — {job['title']}")
            return {"success": True, "message": "Applied successfully"}

        elif continue_btn:
            await continue_btn.click()
            await page.wait_for_load_state("networkidle")
            await _human_delay(1.5, 3)
        else:
            console.print(f"[yellow]Form navigation stalled for {job['company']}[/yellow]")
            return {"success": False, "message": "Form navigation failed"}

    return {"success": False, "message": "Max steps reached"}


async def _fill_indeed_fields(page: Page, personal: dict, answers: dict):
    """Fill common Indeed application form fields."""
    field_map = {
        'input[name*="fullName"], input[placeholder*="Full name"]': personal.get("full_name", ""),
        'input[name*="firstName"], input[placeholder*="First name"]': personal.get("full_name", "").split(" ")[0],
        'input[name*="lastName"], input[placeholder*="Last name"]': " ".join(personal.get("full_name", "").split(" ")[1:]),
        'input[name*="email"], input[type="email"]': personal.get("email", ""),
        'input[name*="phone"], input[type="tel"]': personal.get("phone", ""),
        'input[name*="city"], input[placeholder*="City"]': personal.get("location", "").split(",")[0],
        'input[name*="linkedin"], input[placeholder*="LinkedIn"]': personal.get("linkedin_url", ""),
    }

    for selector, value in field_map.items():
        if not value:
            continue
        try:
            fields = await page.query_selector_all(selector)
            for field in fields:
                current = await field.input_value()
                if not current:
                    await field.fill(value)
                    await _human_delay(0.2, 0.6)
        except Exception:
            continue


async def _handle_indeed_questions(page: Page, answers: dict):
    """Handle Indeed screening questions (yes/no, experience, etc.)."""
    # Radio button questions
    questions = await page.query_selector_all('[class*="question"], [data-testid*="question"]')

    for q in questions:
        text_el = await q.query_selector('[class*="label"], label, p')
        if not text_el:
            continue

        question_text = (await text_el.inner_text()).lower()

        # Work authorization
        if "authorized" in question_text or "work in" in question_text:
            await _click_radio(q, "yes")

        # Sponsorship
        elif "sponsor" in question_text or "visa" in question_text:
            need = answers.get("require_sponsorship", False)
            await _click_radio(q, "yes" if need else "no")

        # Years of experience (numeric input)
        elif "years" in question_text and "experience" in question_text:
            num_input = await q.query_selector('input[type="number"], input[type="text"]')
            if num_input:
                current = await num_input.input_value()
                if not current:
                    await num_input.fill(str(answers.get("years_experience", "3")))
                    await _human_delay(0.2, 0.5)

        await _human_delay(0.1, 0.3)


async def _click_radio(container, answer: str):
    """Click a radio button matching the answer text."""
    radios = await container.query_selector_all('input[type="radio"]')
    labels = await container.query_selector_all("label")

    for i, label in enumerate(labels):
        try:
            text = (await label.inner_text()).lower().strip()
            if text == answer.lower() and i < len(radios):
                await radios[i].click()
                return
        except Exception:
            continue
