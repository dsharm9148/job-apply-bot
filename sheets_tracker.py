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
    "Date",           # A
    "Company",        # B
    "Role",           # C
    "Field",          # D — DS/Engineering | ML/AI | Software Eng | Neuroscience
    "Location",       # E
    "Apply Link",     # F — clickable hyperlink
    "Status",         # G — you update this manually
    "Match Score",    # H
    "Skills Match",   # I
    "Experience Match", # J
    "Industry Match", # K
    "Gaps",           # L
    "ATS Keywords",   # M
    "Resume File",    # N — filename in resumes/tailored/
    "Notes",          # O
]

# Column index map (0-based) for easy reference
COL = {name: i for i, name in enumerate(COLUMNS)}

STATUS_OPTIONS = [
    "Tailored",      # resume ready, not yet applied
    "Applied",       # you submitted the application
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
    creds_path = Path(credentials_file).expanduser().resolve()

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
    field: str,
    job_url: str,
    status: str,
    scores: Optional[dict] = None,
    gaps: Optional[list] = None,
    ats_keywords: Optional[list] = None,
    resume_file: str = "",
    notes: str = "",
    # legacy param kept for backwards compat, unused
    platform: str = "",
    cover_letter: str = "",
) -> str:
    """Append a new application row. Returns the updated range string."""
    ensure_sheet_headers(spreadsheet_id, sheet_name, credentials_file)

    service = _get_service(credentials_file)
    sheet = service.spreadsheets()

    scores = scores or {}

    # Build clickable Apply link — renders as a blue hyperlink in Sheets
    if job_url:
        apply_link = f'=HYPERLINK("{job_url}","Apply")'
    else:
        apply_link = ""

    row = [
        datetime.now().strftime("%Y-%m-%d"),   # A — Date
        company,                                # B — Company
        role,                                   # C — Role
        field,                                  # D — Field
        location,                               # E — Location
        apply_link,                             # F — Apply Link (hyperlink formula)
        status,                                 # G — Status (you update this)
        scores.get("overall", ""),             # H — Match Score
        scores.get("skills_match", ""),        # I — Skills Match
        scores.get("experience_match", ""),    # J — Experience Match
        scores.get("industry_match", ""),      # K — Industry Match
        ", ".join(gaps) if gaps else "",       # L — Gaps
        ", ".join(ats_keywords) if ats_keywords else "",  # M — ATS Keywords
        resume_file,                            # N — Resume File
        notes,                                  # O — Notes
    ]

    result = sheet.values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A:A",
        valueInputOption='USER_ENTERED',
        insertDataOption='INSERT_ROWS',
        body={'values': [row]}
    ).execute()

    updated_range = result.get('updates', {}).get('updatedRange', '')
    console.print(f"[green]Logged to Sheets:[/green] {company} — {role} | {field} | {status}")
    console.print(f"  [dim]Resume: {resume_file}[/dim]")
    if job_url:
        console.print(f"  [dim]Apply:  {job_url}[/dim]")
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
    for i, row in enumerate(rows[1:], start=2):  # skip header, 1-indexed rows
        if len(row) >= 3:
            row_company = row[COL["Company"]].lower().strip()
            row_role = row[COL["Role"]].lower().strip()
            if company.lower() in row_company and role.lower() in row_role:
                # Status = column G (index 6, 1-indexed letter G)
                status_col_letter = chr(ord('A') + COL["Status"])
                sheet.values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{sheet_name}!{status_col_letter}{i}",
                    valueInputOption='RAW',
                    body={'values': [[new_status]]}
                ).execute()
                if notes:
                    notes_col_letter = chr(ord('A') + COL["Notes"])
                    sheet.values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f"{sheet_name}!{notes_col_letter}{i}",
                        valueInputOption='RAW',
                        body={'values': [[notes]]}
                    ).execute()
                console.print(f"[green]Updated status:[/green] {company} — {role} → {new_status}")
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

    by_field = {}
    by_status = {}
    for row in today_rows:
        field = row[COL["Field"]] if len(row) > COL["Field"] else "Unknown"
        status = row[COL["Status"]] if len(row) > COL["Status"] else "Unknown"
        by_field[field] = by_field.get(field, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "today_total": len(today_rows),
        "by_field": by_field,
        "by_status": by_status,
        "total_all_time": len(rows),
    }


def get_row(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    row_number: int,
) -> dict | None:
    """
    Read a single data row by 1-based row number (row 1 = header, row 2 = first data row).
    Returns a dict keyed by column name, or None if row doesn't exist.
    """
    service = _get_service(credentials_file)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A{row_number}:O{row_number}"
    ).execute()

    values = result.get('values', [])
    if not values:
        return None

    row = values[0]
    # Pad to full width
    row += [''] * (len(COLUMNS) - len(row))
    return {col: row[i] for i, col in enumerate(COLUMNS)}


def get_first_row_by_status(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    status: str = 'To Apply',
) -> tuple[int, dict] | tuple[None, None]:
    """
    Find the first row with a given status.
    Returns (row_number, row_dict) or (None, None).
    """
    service = _get_service(credentials_file)
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A:O"
    ).execute()

    rows = result.get('values', [])
    for i, row in enumerate(rows[1:], start=2):  # skip header
        row += [''] * (len(COLUMNS) - len(row))
        row_status = row[COL["Status"]]
        if row_status.lower() == status.lower():
            return i, {col: row[j] for j, col in enumerate(COLUMNS)}

    return None, None


def update_row_after_tailor(
    spreadsheet_id: str,
    sheet_name: str,
    credentials_file: str,
    row_number: int,
    scores: dict,
    gaps: list,
    ats_keywords: list,
    resume_file: str,
    status: str = 'Tailored',
    notes: str = '',
):
    """Update an existing row with tailoring results."""
    service = _get_service(credentials_file)

    # Columns H–O (indices 7–14)
    values = [[
        scores.get('overall', ''),
        scores.get('skills_match', ''),
        scores.get('experience_match', ''),
        scores.get('industry_match', ''),
        ', '.join(gaps) if gaps else '',
        ', '.join(ats_keywords) if ats_keywords else '',
        resume_file,
        notes,
    ]]

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!H{row_number}:O{row_number}",
        valueInputOption='USER_ENTERED',
        body={'values': values}
    ).execute()

    # Update status (col G)
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!G{row_number}",
        valueInputOption='RAW',
        body={'values': [[status]]}
    ).execute()

    console.print(f"[green]Row {row_number} updated → {status}[/green]")
