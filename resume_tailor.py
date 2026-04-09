"""
Resume tailoring helpers.
prep_for_claude() bundles base resume + JD into a prompt for Claude Code.
save_tailored_resume() saves the result to disk.
"""

import re
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel

console = Console()


def extract_resume_text(pdf_path: str) -> str:
    """Extract plain text from a PDF resume."""
    path = Path(pdf_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {path}")

    console.print(f"[dim]Extracting text from {path.name}...[/dim]")
    text = extract_text(str(path))

    # Clean up excessive whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def prep_for_claude(
    resume_text: str,
    job_description: str,
    company: str,
    role: str,
) -> str:
    """
    Returns a ready-to-paste prompt for Claude Code to tailor the resume.
    No API key needed — Claude Code handles the intelligence.
    """
    return f"""You are an expert resume writer and ATS optimization specialist.
Tailor this resume for the job below. Keep all facts true — do not invent experience.

## TARGET JOB
Company: {company}
Role: {role}

## JOB DESCRIPTION
{job_description}

## BASE RESUME
{resume_text}

## INSTRUCTIONS
CRITICAL — this resume will be applied as text replacements to a formatted Google Doc,
so you MUST preserve the exact structure:

1. Keep EVERY bullet point — do not add, remove, or reorder bullets within any entry.
   Just rephrase each bullet to incorporate exact keywords and phrases from the JD.

2. Replace the [SUMMARY] line(s) with 1-2 sentences targeting this specific role/company.

3. Do NOT change: name, contact info, section headers, company names, job titles, dates,
   education details, or the skills section lines.

4. Output the full resume using the SAME structure as the input. Use markdown:
   - ## for section headers (EDUCATION, WORK EXPERIENCE, etc.)
   - ### for entry headers (Company — Location)
   - plain text for title/date lines
   - - for bullet points
   - Plain paragraph for the summary (no bullet)

5. Score the match honestly (1-10): skills_match, experience_match, industry_match, overall.

6. List the exact ATS keywords you added from the JD.

Return ONLY a JSON object — no explanation, no markdown fences:
{{
  "tailored_resume": "FULL RESUME IN MARKDOWN",
  "scores": {{"skills_match": 8, "experience_match": 7, "industry_match": 9, "overall": 8}},
  "gaps": ["gap 1", "gap 2"],
  "ats_keywords_added": ["keyword1", "keyword2"]
}}"""


def save_tailored_resume(
    tailored_text: str,
    company: str,
    role: str,
    output_dir: str,
) -> str:
    """Save tailored resume as a .md file. Returns the file path."""
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    safe_company = re.sub(r'[^\w\s-]', '', company).strip().replace(' ', '_')
    safe_role    = re.sub(r'[^\w\s-]', '', role).strip().replace(' ', '_')
    date_str     = datetime.now().strftime("%Y%m%d")
    filename     = f"{safe_company}_{safe_role}_{date_str}.md"
    filepath     = output_path / filename

    filepath.write_text(tailored_text, encoding='utf-8')
    console.print(f"[green]Saved:[/green] {filepath}")
    return str(filepath)
