# Job Apply Bot

AI-powered job application automation. Uses Claude to tailor your resume for each position, auto-applies on LinkedIn Easy Apply, Indeed, Greenhouse, Lever, and Workday, and tracks every application in Google Sheets.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
   - [Personal Info & Resume](#personal-info--resume)
   - [Job Search Settings](#job-search-settings)
   - [Rate Limits](#rate-limits)
   - [Claude API](#claude-api)
   - [Google Sheets Setup](#google-sheets-setup)
   - [Platform Credentials](#platform-credentials)
   - [Application Form Answers](#application-form-answers)
   - [Skip Filters](#skip-filters)
5. [Usage](#usage)
   - [Recommended First Run (Dry Run)](#recommended-first-run-dry-run)
   - [Full Automated Pipeline](#full-automated-pipeline)
   - [Tailor One Resume Manually](#tailor-one-resume-manually)
   - [Apply to One Specific Job](#apply-to-one-specific-job)
   - [Log a Manual Application](#log-a-manual-application)
   - [View Your Stats](#view-your-stats)
6. [Claude Code Skill (/apply-jobs)](#claude-code-skill-apply-jobs)
7. [Google Sheets Tracker](#google-sheets-tracker)
8. [Rate Limits & Anti-Ban](#rate-limits--anti-ban)
9. [Supported Platforms](#supported-platforms)
10. [File Structure](#file-structure)
11. [Troubleshooting](#troubleshooting)
12. [Disclaimer](#disclaimer)

---

## How It Works

The bot runs a four-stage pipeline:

```
1. SCRAPE   →  Searches LinkedIn/Indeed for jobs matching your titles + locations
2. TAILOR   →  Sends your resume + job description to Claude → gets ATS-optimized resume back
3. APPLY    →  Opens a real browser (Playwright), fills out and submits the application
4. LOG      →  Records every application in Google Sheets with scores, status, and resume file
```

Claude analyzes the job description, rewrites your resume bullets to mirror the exact language used, adds ATS keywords, adjusts the summary, and scores the match 1–10. If the score is below your threshold, the job is skipped entirely.

---

## Prerequisites

- **Python 3.11+**
- **A Claude API key** — get one at [console.anthropic.com](https://console.anthropic.com)
- **Your resume as a PDF** — your master/base resume that will be tailored for each job
- **A Google account** — for the Sheets tracker
- **LinkedIn and/or Indeed account** — for applying
- **Claude Code** (optional) — for the `/apply-jobs` slash command

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/diya-sharma5/job-apply-bot.git
cd job-apply-bot
```

Or if you already have it locally:

```bash
cd ~/job-apply
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the browser engine

Playwright needs a browser to automate. Install Chromium:

```bash
playwright install chromium
```

This downloads a ~150MB Chromium binary. Only needs to be done once.

### 5. Set your Claude API key

```bash
export ANTHROPIC_API_KEY="sk-ant-api03-..."
```

To make this permanent, add it to your shell profile:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-api03-..."' >> ~/.zshrc
source ~/.zshrc
```

---

## Configuration

Copy the example config and edit it:

```bash
cp config.yaml.example config.yaml
```

Open `config.yaml` in any editor. Here is a full walkthrough of every section:

---

### Personal Info & Resume

```yaml
personal:
  full_name: "Jane Smith"
  email: "jane@email.com"
  phone: "415-555-1234"
  location: "San Francisco, CA"
  linkedin_url: "https://linkedin.com/in/janesmith"
  github_url: "https://github.com/janesmith"
  portfolio_url: "https://janesmith.dev"   # leave blank if none
  years_experience: 6

resume:
  base_pdf: "~/Documents/resume.pdf"     # ← path to your PDF resume
  output_dir: "~/job-apply/tailored"     # tailored .docx files saved here
```

- `base_pdf` must point to a real PDF file. This is read once and sent to Claude for each tailoring.
- `output_dir` is created automatically if it doesn't exist. Each tailored resume is saved as `Company_Role_YYYYMMDD.docx`.

---

### Job Search Settings

```yaml
search:
  job_titles:
    - "Software Engineer"
    - "Senior Software Engineer"
    - "Backend Engineer"
  locations:
    - "Remote"
    - "San Francisco, CA"
    - "New York, NY"
  keywords:
    - "Python"
    - "AWS"
  excluded_companies:
    - "Amazon"         # will be skipped even if matched
  min_salary: 130000   # 0 to disable
  experience_levels:
    - "mid"
    - "senior"         # options: entry, mid, senior, director
```

- The scraper searches every combination of `job_titles × locations`.
- `excluded_companies` is case-insensitive. Add any companies you don't want to apply to.
- `min_salary` filters LinkedIn/Indeed listings that show a salary range. Many listings don't show salary, so this won't filter those.
- `experience_levels` maps to LinkedIn's filter: `entry` = 1, `mid` = 2, `senior` = 3, `director` = 4.

---

### Rate Limits

```yaml
rate_limits:
  linkedin:
    daily_apply_limit: 25           # max applications per day on LinkedIn
    delay_between_applies_sec: [45, 120]   # random delay range (seconds)
    daily_scrape_limit: 200         # max job listings to collect per day
  indeed:
    daily_apply_limit: 50
    delay_between_applies_sec: [20, 60]
    daily_scrape_limit: 500
  greenhouse_lever_workday:
    daily_apply_limit: 30
    delay_between_applies_sec: [30, 90]
```

> **Important:** LinkedIn is the most aggressive about detecting bots. Keep `daily_apply_limit` at 25 or below and do not reduce the delay range. See [Rate Limits & Anti-Ban](#rate-limits--anti-ban) for details.

---

### Claude API

```yaml
claude:
  model: "claude-sonnet-4-6"    # recommended — fast and high quality
  max_tokens: 4096
```

Available models (best to fastest/cheapest):
- `claude-opus-4-6` — highest quality tailoring, slower, costs more
- `claude-sonnet-4-6` — best balance (recommended)
- `claude-haiku-4-5-20251001` — fastest, lowest cost, slightly less nuanced

---

### Google Sheets Setup

You need a Google Cloud project with the Sheets API enabled. Here are two ways to do it:

#### Option A: Service Account (recommended for automation)

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click **"New Project"** → give it a name → **Create**
3. In the sidebar: **APIs & Services** → **Enable APIs** → search for **Google Sheets API** → Enable
4. Go to **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
5. Give it any name, click **Done**
6. Click the service account you just created → **Keys** tab → **Add Key** → **Create new key** → **JSON**
7. Download the JSON file → save it as `~/job-apply/google_credentials.json`
8. Copy the service account's email address (looks like `name@project.iam.gserviceaccount.com`)
9. Open your Google Sheet → click **Share** → paste that email → give it **Editor** access

Then in `config.yaml`:

```yaml
google_sheets:
  spreadsheet_id: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
  sheet_name: "Applications"
  credentials_file: "~/job-apply/google_credentials.json"
```

**Where is the spreadsheet ID?** It's in the URL of your Google Sheet:
```
https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
```

#### Option B: OAuth (simpler setup, requires browser auth)

1. In Google Cloud Console: **APIs & Services** → **Credentials** → **Create Credentials** → **OAuth client ID**
2. Application type: **Desktop app** → Create
3. Download the JSON → save as `~/job-apply/google_credentials.json`
4. The first time you run the bot, a browser window will open asking you to authorize — click Allow
5. A `token.json` file is created for future runs (no browser needed again)

---

### Platform Credentials

```yaml
linkedin:
  email: "your@email.com"
  password: "yourpassword"

indeed:
  email: "your@email.com"
  password: "yourpassword"
```

These are stored **only on your local machine** in `config.yaml` (which is gitignored). They are never sent anywhere except directly to LinkedIn/Indeed's login page via the browser automation.

> **Tip:** Use a dedicated email for job applications to keep your main inbox clean.

---

### Application Form Answers

These are used to auto-fill common screening questions on application forms:

```yaml
form_answers:
  authorized_to_work: true          # "Are you authorized to work in the US?"
  require_sponsorship: false        # "Do you require visa sponsorship?"
  gender: ""                        # leave blank to skip (EEO question)
  ethnicity: ""                     # leave blank to skip
  veteran_status: ""                # leave blank to skip
  disability_status: ""             # leave blank to skip
  cover_letter_template: |
    Dear Hiring Team,

    I'm excited to apply for the {role} position at {company}. With {years_experience}
    years of experience in {relevant_skills}, I'm confident I can contribute meaningfully.

    {tailored_paragraph}

    Best regards,
    {full_name}
```

The `{tailored_paragraph}` placeholder is filled in by Claude with a job-specific sentence. Leave EEO fields blank to skip them entirely (the bot will not select any option).

---

### Skip Filters

```yaml
skip_if:
  already_applied: true    # won't apply to a URL it has seen before (tracked in logs/seen_urls.json)
  score_below: 6           # skip if Claude's overall match score is below this (1-10)
  requires_degree_not_met: false
```

Setting `score_below: 6` means the bot will tailor and apply to jobs where it rates your fit as 6/10 or higher. Increase to 7 or 8 to be more selective.

---

## Usage

### Recommended First Run (Dry Run)

Always test with `--dry-run` first. This scrapes jobs and tailors resumes but **does not submit any applications** or write to Google Sheets:

```bash
python main.py run --platforms indeed,linkedin --dry-run
```

You'll see:
- How many jobs were found
- Match scores for each
- Which jobs would be skipped
- Tailored resume files generated in `~/job-apply/tailored/`

Review the tailored resumes to make sure the quality is acceptable before going live.

---

### Full Automated Pipeline

Once you're happy with the dry run output:

```bash
# Indeed only (safer to start with)
python main.py run --platforms indeed

# Both platforms
python main.py run --platforms indeed,linkedin

# Override daily limit (use carefully)
python main.py run --platforms indeed --max-apply 30
```

What happens:
1. Scrapes Indeed/LinkedIn for new jobs matching your search config
2. For each job: sends resume + job description to Claude → gets tailored resume
3. Saves tailored resume as `.docx` in `~/job-apply/tailored/`
4. Opens a browser and fills out + submits the application
5. Logs everything to Google Sheets
6. Waits a random delay before the next application
7. Stops when the daily limit is reached

The browser is **visible** (not headless) so you can watch it work and intervene if needed (e.g., if LinkedIn asks for a CAPTCHA or 2FA).

---

### Tailor One Resume Manually

For when you want to craft one high-quality application yourself:

```bash
# Interactive — paste job description when prompted (Ctrl+D when done)
python main.py tailor \
  --company "Stripe" \
  --role "Senior Software Engineer" \
  --url "https://boards.greenhouse.io/stripe/jobs/12345"

# From a text file
python main.py tailor \
  --company "Stripe" \
  --role "Senior Software Engineer" \
  --description-file ~/Downloads/stripe_job.txt

# Tailor only — don't log to Sheets yet
python main.py tailor \
  --company "Stripe" \
  --role "Senior Software Engineer" \
  --dry-run
```

Output:
- Match scores table printed to terminal
- Any skill gaps listed
- Tailored `.docx` saved to `~/job-apply/tailored/`
- Application logged to Google Sheets as "Tailored" status

---

### Apply to One Specific Job

Use this after tailoring, or to apply to a specific URL:

```bash
python main.py apply \
  --url "https://boards.greenhouse.io/stripe/jobs/12345" \
  --resume "~/job-apply/tailored/Stripe_Senior_Software_Engineer_20260319.docx" \
  --company "Stripe" \
  --role "Senior Software Engineer"
```

The `--platform` flag is optional — the bot auto-detects from the URL:
- `greenhouse.io` → Greenhouse
- `lever.co` → Lever
- `myworkdayjobs.com` → Workday
- `linkedin.com` → LinkedIn Easy Apply
- `indeed.com` → Indeed

To force a platform:

```bash
python main.py apply \
  --url "https://..." \
  --resume "~/job-apply/tailored/Company_Role_20260319.docx" \
  --platform greenhouse
```

To test without submitting:

```bash
python main.py apply \
  --url "https://..." \
  --resume "~/job-apply/tailored/..." \
  --dry-run
```

---

### Log a Manual Application

If you applied somewhere manually (directly on a company's site, for example):

```bash
python main.py log \
  --company "Airbnb" \
  --role "Staff Engineer" \
  --location "Remote" \
  --url "https://careers.airbnb.com/positions/12345/" \
  --score 8 \
  --status "Applied" \
  --resume-file "~/job-apply/tailored/Airbnb_Staff_Engineer_20260319.docx"
```

Valid `--status` values: `Tailored`, `Applied`, `No Response`, `Rejected`, `Phone Screen`, `Interview`, `Final Round`, `Offer`, `Accepted`, `Declined`

---

### View Your Stats

```bash
python main.py stats
```

Prints a table showing today's applications broken down by platform and status, plus all-time totals.

Example output:

```
        Application Stats — Today
┌──────────────────────────┬───────┐
│ Metric                   │ Count │
├──────────────────────────┼───────┤
│ Today's Applications     │    23 │
│ All-Time Total           │   147 │
├──────────────────────────┼───────┤
│   linkedin               │     8 │
│   indeed                 │    15 │
├──────────────────────────┼───────┤
│   Applied                │    21 │
│   Tailored               │     2 │
└──────────────────────────┴───────┘
```

---

## Claude Code Skill (/apply-jobs)

If you use Claude Code (Anthropic's CLI), the `/apply-jobs` skill lets you tailor a resume interactively inside a conversation.

### Setup

The skill file is already installed at `~/.claude/commands/apply-jobs.md` when you clone this repo. If it's not there:

```bash
mkdir -p ~/.claude/commands
cp apply-jobs-skill.md ~/.claude/commands/apply-jobs.md
```

### How to use it

1. Open Claude Code in any directory
2. Type `/apply-jobs`
3. Paste the job description when prompted
4. Claude will:
   - Extract the company, role, requirements, and ATS keywords
   - Ask for your resume path
   - Tailor the resume content and print it in full
   - Score your match (1–10 across skills, experience, industry)
   - Give you the exact `python main.py` commands to save, apply, and log

This is ideal for high-priority applications where you want to review the tailored resume before submitting.

---

## Google Sheets Tracker

Every application (automated or manual) is logged as a row in your Google Sheet with these columns:

| Column | What It Contains |
|--------|-----------------|
| **Date Applied** | Timestamp of when the application was submitted |
| **Company** | Company name |
| **Role** | Exact job title |
| **Location** | City, state, or "Remote" |
| **Platform** | linkedin / indeed / greenhouse / lever / workday / manual |
| **Job URL** | Direct link to the job posting |
| **Status** | Current status (see below) |
| **Match Score** | Claude's overall fit rating (1–10) |
| **Skills Match** | Technical skills alignment (1–10) |
| **Experience Match** | Seniority level alignment (1–10) |
| **Industry Match** | Industry/domain relevance (1–10) |
| **Gaps** | Requirements you're missing (if any) |
| **ATS Keywords Added** | Keywords Claude added to your resume |
| **Resume File** | Path to the tailored `.docx` file |
| **Cover Letter** | First 200 chars of the cover letter used |
| **Response** | Fill in manually when you hear back |
| **Interview Date** | Fill in manually when scheduled |
| **Offer** | Fill in manually if you receive an offer |
| **Notes** | Any notes you want to add |

### Status lifecycle

```
Tailored → Applied → No Response
                   → Phone Screen → Interview → Final Round → Offer → Accepted
                                                                      → Declined
                   → Rejected
```

Update status manually in the sheet, or use:

```bash
python main.py log --company "Stripe" --role "SWE" --status "Phone Screen"
```

---

## Rate Limits & Anti-Ban

### LinkedIn

LinkedIn has aggressive bot detection and **will ban accounts** that apply at high volume. The bot uses several techniques to stay under the radar:

- **Visible browser** (not headless) — harder to detect than headless Chrome
- **Random delays** between every action (keystrokes, clicks, page loads)
- **Human-like typing** — characters typed one at a time with random intervals
- **Random wait between applications** — configurable range, defaults to 45–120 seconds
- **Daily hard limit** — stops at 25 applications by default

**Recommended LinkedIn settings:**
```yaml
rate_limits:
  linkedin:
    daily_apply_limit: 25
    delay_between_applies_sec: [60, 150]
    daily_scrape_limit: 150
```

If LinkedIn shows a CAPTCHA or sends a verification email, the bot will pause and wait for you to complete it manually.

### Indeed

More automation-tolerant, but still use reasonable limits:
```yaml
rate_limits:
  indeed:
    daily_apply_limit: 40
    delay_between_applies_sec: [25, 70]
```

### Greenhouse / Lever / Workday

These ATS platforms don't have user-level rate limiting (each job is on a different company's domain), but be sensible:
```yaml
rate_limits:
  greenhouse_lever_workday:
    daily_apply_limit: 30
    delay_between_applies_sec: [30, 90]
```

---

## Supported Platforms

| Platform | Auto-Detect | Scraping | Applying | Notes |
|----------|-------------|----------|----------|-------|
| LinkedIn Easy Apply | ✅ | ✅ | ✅ | Easy Apply only; rate limit carefully |
| Indeed | ✅ | ✅ | ✅ | Most reliable |
| Greenhouse | ✅ | — | ✅ | Very common ATS (Stripe, Airbnb, etc.) |
| Lever | ✅ | — | ✅ | Common for tech startups |
| Workday | ✅ | — | ✅ | May require account creation on first use |
| SmartRecruiters | ✅ | — | ✅ | Basic support |
| Taleo / iCIMS | Detected | — | ❌ | Detected but not yet automated |

For platforms not listed, use `python main.py tailor` + apply manually, then `python main.py log` to track it.

---

## File Structure

```
job-apply-bot/
├── main.py                        # CLI — all commands live here
├── resume_tailor.py               # PDF extraction + Claude API + DOCX output
├── sheets_tracker.py              # Google Sheets read/write
├── config.yaml.example            # Configuration template (copy to config.yaml)
├── requirements.txt               # Python dependencies
├── .gitignore                     # Excludes config.yaml, credentials, tailored resumes
│
├── scrapers/
│   ├── linkedin_scraper.py        # Logs in, searches, collects job listings
│   └── indeed_scraper.py          # Searches Indeed, collects job listings
│
├── appliers/
│   ├── linkedin_applier.py        # Fills out LinkedIn Easy Apply multi-step forms
│   ├── indeed_applier.py          # Handles Indeed's application flow
│   └── ats_applier.py             # Greenhouse, Lever, Workday, SmartRecruiters
│
├── tailored/                      # Generated tailored resumes (gitignored)
│   └── Company_Role_YYYYMMDD.docx
│
└── logs/
    └── seen_urls.json             # URLs already applied to (prevents duplicates)

~/.claude/commands/
└── apply-jobs.md                  # Claude Code /apply-jobs skill
```

**Files you create (gitignored, never committed):**
- `config.yaml` — your personal config
- `google_credentials.json` — Google API credentials
- `token.json` — Google OAuth token (auto-created)
- `tailored/` — your tailored resumes
- `logs/` — run state and seen URLs

---

## Troubleshooting

### "Resume not found"
Make sure `resume.base_pdf` in `config.yaml` points to an existing file:
```bash
ls -la ~/Documents/resume.pdf
```

### "Config not found"
```bash
cp config.yaml.example config.yaml
# then edit config.yaml
```

### LinkedIn asks for CAPTCHA or 2FA
The browser is visible so you can solve it manually. The bot will pause and wait. If this happens frequently, reduce your `daily_apply_limit` and increase delays.

### "No Google Sheets configured"
Set `google_sheets.spreadsheet_id` in `config.yaml`. The ID is the long string in your sheet's URL.

### Google Sheets authentication fails
- **Service account**: make sure the sheet is shared with the service account email
- **OAuth**: delete `token.json` and re-run to re-authenticate

### "No Easy Apply button found" on LinkedIn
The job may not have Easy Apply, or LinkedIn changed their HTML. The bot skips these jobs and logs them as skipped.

### Workday asks to create an account
Workday requires a unique account per company. The bot will pause and ask you to create the account manually, then continue filling out the form.

### Claude returns invalid JSON
Rare — Claude occasionally wraps output in markdown. The parser strips code fences automatically. If it persists, try switching to `claude-opus-4-6` in the config (more instruction-following).

### Applications are going too fast / getting flagged
Increase the delay range in `config.yaml`:
```yaml
delay_between_applies_sec: [90, 180]
```

---

## Disclaimer

Automated job applications may violate the Terms of Service of LinkedIn, Indeed, and other platforms. This tool is provided for educational and personal productivity purposes. You are responsible for how you use it. Review your tailored resumes before submitting to ensure accuracy — Claude tailors based on your actual resume content and will not fabricate experience, but always verify the output.

Use reasonable rate limits. Do not run hundreds of applications per day on LinkedIn. Respect the platforms.
