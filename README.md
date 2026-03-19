# Job Apply Bot

AI-powered job application automation. Scrapes jobs from LinkedIn, Indeed, and ATS platforms, tailors your resume using Claude, and auto-applies — logging everything to Google Sheets.

## Features

- **Resume tailoring** via Claude API — mirrors job keywords for ATS optimization
- **Auto-apply** to LinkedIn Easy Apply, Indeed, Greenhouse, Lever, Workday, SmartRecruiters
- **Google Sheets tracker** — logs every application with match scores, status, resume file
- **Claude Code skill** — `/apply-jobs` slash command for manual one-off applications
- **Rate limiting** — configurable daily limits and human-like delays to avoid bans

## Setup

### 1. Install dependencies

```bash
cd ~/job-apply
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure

```bash
cp config.yaml.example config.yaml
```

Edit `config.yaml` with:
- Your personal info and resume path
- Job titles and locations to search
- LinkedIn/Indeed credentials
- Claude API key (or set `ANTHROPIC_API_KEY` env var)
- Google Sheets spreadsheet ID

### 3. Set up Google Sheets API

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable "Google Sheets API"
3. Create a Service Account → Download credentials JSON
4. Save as `~/job-apply/google_credentials.json`
5. Share your Google Sheet with the service account email

OR use OAuth:
1. Create OAuth 2.0 credentials (Desktop app type)
2. Download as `~/job-apply/google_credentials.json`
3. First run will open a browser to authenticate

### 4. Set your Claude API key

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

Or add to `~/.zshrc` / `~/.bashrc`.

---

## Usage

### Full automated pipeline (scrape + tailor + apply)

```bash
# Dry run first to see what it finds
python main.py run --platforms indeed,linkedin --dry-run

# Live run (applies up to daily limits in config)
python main.py run --platforms indeed,linkedin
```

### Tailor resume for a specific job

```bash
# Paste job description interactively
python main.py tailor --company "Stripe" --role "Senior Software Engineer" --url "https://..."

# From a file
python main.py tailor --company "Stripe" --role "Backend Engineer" --description-file job.txt
```

### Apply to a specific job

```bash
python main.py apply \
  --url "https://boards.greenhouse.io/stripe/jobs/12345" \
  --resume "~/job-apply/tailored/Stripe_Senior_Software_Engineer_20260101.docx" \
  --company "Stripe" \
  --role "Senior Software Engineer"
```

### Log a manual application

```bash
python main.py log \
  --company "Stripe" \
  --role "Backend Engineer" \
  --url "https://..." \
  --score 9 \
  --status "Applied"
```

### View stats

```bash
python main.py stats
```

### Claude Code skill

In any Claude Code session, type:
```
/apply-jobs
```
Then paste a job description or URL. Claude will tailor your resume and give you the exact commands to run.

---

## Rate Limits (Important)

LinkedIn **actively bans** accounts that apply at high volumes. Defaults:

| Platform | Daily Apply Limit | Delay Between |
|----------|------------------|---------------|
| LinkedIn | 25/day | 45–120s random |
| Indeed | 50/day | 20–60s random |
| Greenhouse/Lever/Workday | 30/day | 30–90s random |

You can increase these in `config.yaml` but do so at your own risk for LinkedIn.

---

## Google Sheets Columns

| Column | Description |
|--------|-------------|
| Date Applied | Timestamp |
| Company | Company name |
| Role | Job title |
| Location | City/Remote |
| Platform | linkedin/indeed/greenhouse/etc |
| Job URL | Direct link |
| Status | Tailored/Applied/Phone Screen/Interview/Offer/etc |
| Match Score | Overall fit (1–10) |
| Skills Match | Skills fit (1–10) |
| Experience Match | Seniority fit (1–10) |
| Industry Match | Industry fit (1–10) |
| Gaps | Missing requirements |
| ATS Keywords Added | Keywords added for ATS |
| Resume File | Path to tailored resume |
| Cover Letter | Cover letter preview |
| Response | (fill in manually) |
| Interview Date | (fill in manually) |
| Offer | (fill in manually) |
| Notes | Any notes |

---

## File Structure

```
~/job-apply/
├── main.py                   # CLI entrypoint
├── resume_tailor.py          # Claude API resume tailoring
├── sheets_tracker.py         # Google Sheets integration
├── config.yaml               # Your configuration (gitignored)
├── config.yaml.example       # Template
├── requirements.txt
├── scrapers/
│   ├── linkedin_scraper.py   # LinkedIn job scraper
│   └── indeed_scraper.py     # Indeed job scraper
├── appliers/
│   ├── linkedin_applier.py   # LinkedIn Easy Apply bot
│   ├── indeed_applier.py     # Indeed application bot
│   └── ats_applier.py        # Greenhouse/Lever/Workday/SmartRecruiters
├── tailored/                 # Generated tailored resumes (gitignored)
└── logs/                     # seen_urls.json, run logs (gitignored)

~/.claude/commands/
└── apply-jobs.md             # Claude Code /apply-jobs skill
```

---

## Disclaimer

Automated job applications may violate the Terms of Service of LinkedIn and other platforms. Use responsibly, respect rate limits, and review applications before submission where possible. This tool is provided for educational and productivity purposes.
