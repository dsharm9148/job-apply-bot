"""
LinkedIn Easy Apply bot using Playwright.
Fills out the Easy Apply form with resume + standard answers.

RATE LIMIT: Default 25/day. LinkedIn detects high-volume applying.
"""

import asyncio
import random
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Page
from rich.console import Console

console = Console()


async def _human_delay(min_sec: float = 0.5, max_sec: float = 2.0):
    await asyncio.sleep(random.uniform(min_sec, max_sec))


async def apply_linkedin_easy_apply(
    page: Page,
    job: dict,
    resume_path: str,
    config: dict,
    dry_run: bool = False,
) -> dict:
    """
    Apply to a single LinkedIn Easy Apply job.
    Returns result dict: {success, skipped, error, message}
    """
    personal = config.get("personal", {})
    answers = config.get("form_answers", {})

    console.print(f"[blue]Applying:[/blue] {job['company']} — {job['title']}")

    await page.goto(job["url"])
    await page.wait_for_load_state("networkidle")
    await _human_delay(2, 4)

    # Click Easy Apply button
    try:
        easy_apply_btn = await page.wait_for_selector(
            '.jobs-apply-button--top-card button, [data-control-name="jobdetails_topcard_inapply"]',
            timeout=8000
        )
    except Exception:
        return {"success": False, "skipped": True, "message": "No Easy Apply button found"}

    if dry_run:
        console.print(f"[yellow][DRY RUN] Would apply to {job['company']} — {job['title']}[/yellow]")
        return {"success": True, "skipped": False, "dry_run": True, "message": "Dry run"}

    await easy_apply_btn.click()
    await _human_delay(1.5, 3)

    # Multi-step form handler
    max_steps = 10
    for step in range(max_steps):
        # Check if form is still open
        modal = await page.query_selector('.jobs-easy-apply-modal, [data-test-modal="easy-apply-modal"]')
        if not modal:
            break

        # Handle file upload (resume)
        upload_input = await page.query_selector('input[type="file"]')
        if upload_input:
            resume_abs = str(Path(resume_path).expanduser().resolve())
            await upload_input.set_input_files(resume_abs)
            await _human_delay(1, 2)

        # Handle phone number field
        phone_field = await page.query_selector('input[id*="phoneNumber"], input[name*="phone"]')
        if phone_field:
            current_val = await phone_field.input_value()
            if not current_val:
                await phone_field.fill(personal.get("phone", ""))
                await _human_delay(0.3, 0.8)

        # Handle yes/no radio questions
        await _handle_radio_questions(page, answers)

        # Handle text questions
        await _handle_text_questions(page, personal, answers)

        # Handle select/dropdown questions
        await _handle_select_questions(page, answers)

        # Look for Next/Review/Submit button
        next_btn = await page.query_selector('button[aria-label="Continue to next step"], button[aria-label="Review your application"]')
        submit_btn = await page.query_selector('button[aria-label="Submit application"]')

        if submit_btn:
            await submit_btn.click()
            await _human_delay(2, 4)
            console.print(f"[green]Applied:[/green] {job['company']} — {job['title']}")
            return {"success": True, "skipped": False, "message": "Applied successfully"}

        if next_btn:
            await next_btn.click()
            await _human_delay(1, 2.5)
        else:
            # Try generic "Next" button
            buttons = await page.query_selector_all('button')
            next_found = False
            for btn in buttons:
                text = await btn.inner_text()
                if text.strip().lower() in ("next", "continue", "review"):
                    await btn.click()
                    next_found = True
                    await _human_delay(1, 2)
                    break

            if not next_found:
                console.print(f"[yellow]Couldn't advance form for {job['company']}[/yellow]")
                # Close modal
                close_btn = await page.query_selector('button[aria-label="Dismiss"], [data-test-modal-close-btn]')
                if close_btn:
                    await close_btn.click()
                return {"success": False, "skipped": False, "message": "Form navigation failed"}

    return {"success": False, "skipped": False, "message": "Max form steps reached"}


async def _handle_radio_questions(page: Page, answers: dict):
    """Auto-answer Yes/No radio button questions."""
    fieldsets = await page.query_selector_all("fieldset")

    for fieldset in fieldsets:
        legend = await fieldset.query_selector("legend span")
        if not legend:
            continue

        question_text = (await legend.inner_text()).lower()

        # Determine answer
        if "authorized" in question_text or "eligible" in question_text:
            answer = "yes" if answers.get("authorized_to_work", True) else "no"
        elif "sponsor" in question_text or "visa" in question_text:
            answer = "yes" if answers.get("require_sponsorship", False) else "no"
        elif "18" in question_text and "age" in question_text:
            answer = "yes"
        elif "background check" in question_text:
            answer = "yes"
        elif "drug test" in question_text:
            answer = "yes"
        elif "relocat" in question_text:
            answer = "yes"
        elif "remote" in question_text:
            answer = "yes"
        else:
            continue

        # Click the appropriate radio
        radios = await fieldset.query_selector_all('input[type="radio"]')
        labels = await fieldset.query_selector_all("label")

        for i, label in enumerate(labels):
            label_text = (await label.inner_text()).lower()
            if label_text == answer and i < len(radios):
                await radios[i].click()
                await _human_delay(0.2, 0.5)
                break


async def _handle_text_questions(page: Page, personal: dict, answers: dict):
    """Fill text input questions."""
    text_inputs = await page.query_selector_all('input[type="text"]:not([value])')

    for inp in text_inputs:
        label_id = await inp.get_attribute("aria-labelledby") or ""
        placeholder = (await inp.get_attribute("placeholder") or "").lower()
        name = (await inp.get_attribute("name") or "").lower()

        # Try to figure out what the field is asking
        if "years" in placeholder or "experience" in placeholder or "years" in name:
            await inp.fill(str(personal.get("years_experience", "3")))
        elif "salary" in placeholder or "compensation" in placeholder:
            min_sal = answers.get("form_answers", {}).get("expected_salary", "")
            if min_sal:
                await inp.fill(str(min_sal))
        elif "linkedin" in placeholder or "linkedin" in name:
            await inp.fill(personal.get("linkedin_url", ""))
        elif "github" in placeholder or "github" in name:
            await inp.fill(personal.get("github_url", ""))
        elif "portfolio" in placeholder or "website" in placeholder:
            await inp.fill(personal.get("portfolio_url", ""))

        await _human_delay(0.1, 0.4)


async def _handle_select_questions(page: Page, answers: dict):
    """Handle dropdown select questions."""
    selects = await page.query_selector_all("select")

    for sel in selects:
        name = (await sel.get_attribute("name") or "").lower()
        options = await sel.query_selector_all("option")
        option_texts = [await o.inner_text() for o in options]

        # Gender
        if "gender" in name:
            val = answers.get("gender", "")
            if val:
                await sel.select_option(label=val)

        # Ethnicity
        elif "ethnicity" in name or "race" in name:
            val = answers.get("ethnicity", "")
            if val:
                await sel.select_option(label=val)

        # Veteran status
        elif "veteran" in name:
            val = answers.get("veteran_status", "")
            if val:
                await sel.select_option(label=val)

        # Disability
        elif "disability" in name:
            val = answers.get("disability_status", "")
            if val:
                await sel.select_option(label=val)

        await _human_delay(0.1, 0.3)
