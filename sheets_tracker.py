"""
Google Sheets tracker for job applications.
Logs each application with status, scores, and metadata.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from rich.console import Console

console = Console()

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

COLUMNS = [
    "Date Applied",
    "Company",
    "Role",
    "Location",
    "Platform",
    "Job URL",
    "Status",
    "Match Score",
    "Skills Match",
    "Experience Match",
    "Industry Match",
    "Gaps",
    "ATS Keywords Added",
    "Resume File",
    "Cover Letter",
    "Response",
    "Interview Date",
    "Offer",
    "Notes",
]

STATUS_OPTIONS = [
    "Tailored",      # resume tailored, not yet applied
    "Applied",       # application submitted
    "No Response",   # ghosted
    "Rejected",      # rejection received
    "Phone Screen",  # phone screen scheduled/completed
    "Interview",     # interview stage
    "Final Round",   # final interview
    "Offer",         # offer received
    "Accepted",      # offer accepted
    "Declined",      # offer declined
]


def _get_service(credentials_file: str):
    """Authenticate and return Sheets API service."""
    creds_path = Path(credentials_file).expanduser()

    # Try service account first
    if creds_path.exists():
        try:
            creds = service_account.Credentials.from_service_account_file(
                str(creds_path), scopes=SCOPES
            )
            return build('sheets', 'v4', credentials=creds)
        except Exception:
            pass

    # Fall back to OAuth
    token_path = Path("~/job-apply/token.json").expanduser()
    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(str(token_path), 'w') as f:
            f.write(creds.to_json())

    return build('sheets', 'v4', credentials=creds)


def ensure_sheet_headers(spreadsheet_id: str, sheet_name: str, credentials_file: str):
    """Create header row if sheet is empty."""
    service = _get_service(credentials_file)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A1:A1"
    ).execute()

    values = result.get('values', [])
    if not values:
        # Write headers
        sheet.values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{sheet_name}!A1",
            valueInputOption='RAW',
            body={'values': [COLUMNS]}
        ).execute()

        # Bold the header row
        sheet_id = _get_sheet_id(service, spreadsheet_id, sheet_name)
        sheet.batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": 0,
                                "endRowIndex": 1
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.6},
                                    "textFormat": {
                                        "bold": True,
                                        "foregroundColor": {"red": 1, "green": 1, "blue": 1}
                                    }
                                }
                            },
                            "fields": "userEnteredFormat(textFormat,backgroundColor)"
                        }
                    },
                    {
                        "autoResizeDimensions": {
                            "dimensions": {
                                "sheetId": sheet_id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": len(COLUMNS)
                            }
                        }
                    }
                ]
            }
        ).execute()
        console.print("[green]Created sheet headers[/green]")


def _get_sheet_id(service, spreadsheet_id: str, sheet_name: str) -> int:
    """Get numeric sheet ID by name."""
    spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in spreadsheet['sheets']:
        if sheet['properties']['title'] == sheet_name:
            return sheet['properties']['sheetId']
    raise ValueError(f"Sheet '{sheet_name}' not found")


def log_application(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    company: str,
    role: str,
    location: str,
    platform: str,
    job_url: str,
    status: str,
    scores: Optional[dict] = None,
    gaps: Optional[list] = None,
    ats_keywords: Optional[list] = None,
    resume_file: str = "",
    cover_letter: str = "",
    notes: str = "",
) -> int:
    """Append a new application row. Returns the row number."""
    ensure_sheet_headers(spreadsheet_id, sheet_name, credentials_file)

    service = _get_service(credentials_file)
    sheet = service.spreadsheets()

    scores = scores or {}
    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        company,
        role,
        location,
        platform,
        job_url,
        status,
        scores.get("overall", ""),
        scores.get("skills_match", ""),
        scores.get("experience_match", ""),
        scores.get("industry_match", ""),
        ", ".join(gaps) if gaps else "",
        ", ".join(ats_keywords) if ats_keywords else "",
        resume_file,
        cover_letter[:200] if cover_letter else "",  # truncate
        "",   # Response (filled later)
        "",   # Interview Date
        "",   # Offer
        notes,
    ]

    result = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A:A",
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [row]}
    ).execute()

    updated_range = result.get('updates', {}).get('updatedRange', '')
    console.print(f"[green]Logged to Google Sheets:[/green] {company} — {role} ({status})")
    return updated_range


def update_status(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    company: str,
    role: str,
    new_status: str,
    notes: str = "",
):
    """Find and update the status of an existing application."""
    service = _get_service(credentials_file)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A:S"
    ).execute()

    rows = result.get('values', [])
    for i, row in enumerate(rows[1:], start=2):  # skip header
        if len(row) >= 3:
            row_company = row[1].lower().strip()
            row_role = row[2].lower().strip()
            if company.lower() in row_company and role.lower() in row_role:
                # Update status column (G = index 6)
                sheet.values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!G{i}",
                    valueInputOption='RAW',
                    body={'values': [[new_status]]}
                ).execute()
                if notes:
                    sheet.values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f"{sheet_name}!S{i}",
                        valueInputOption='RAW',
                        body={'values': [[notes]]}
                    ).execute()
                console.print(f"[green]Updated status:[/green] {company} → {new_status}")
                return

    console.print(f"[yellow]Application not found in sheet:[/yellow] {company} — {role}")


def get_daily_stats(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
) -> dict:
    """Return today's application stats from the sheet."""
    service = _get_service(credentials_file)
    sheet = service.spreadsheets()

    result = sheet.values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A:H"
    ).execute()

    today = datetime.now().strftime("%Y-%m-%d")
    rows = result.get('values', [])[1:]  # skip header

    today_rows = [r for r in rows if r and r[0].startswith(today)]

    by_platform = {}
    by_status = {}
    for row in today_rows:
        platform = row[4] if len(row) > 4 else "Unknown"
        status = row[6] if len(row) > 6 else "Unknown"
        by_platform[platform] = by_platform.get(platform, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "today_total": len(today_rows),
        "by_platform": by_platform,
        "by_status": by_status,
        "total_all_time": len(rows),
    }
