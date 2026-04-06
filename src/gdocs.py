"""
Google Docs / Drive integration for resume management.

Workflow:
  1. python main.py setup-gdocs          # creates folder + 4 base template docs in Drive
  2. save-tailored automatically creates a per-job Google Doc and stores its link in Sheets
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from rich.console import Console

console = Console()

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

ROOT_FOLDER_NAME = "Job Application Resumes"
BASE_FOLDER_NAME = "Base Templates"

FIELD_DOC_TITLES = {
    "data_science": "Base Resume — Data Science",
    "ml_ai":        "Base Resume — ML / AI",
    "software_eng": "Base Resume — Software Engineering",
    "neuroscience": "Base Resume — Neuroscience Research",
}

FIELD_FILES = {
    "data_science": "data_science.md",
    "ml_ai":        "ml_ai.md",
    "software_eng": "software_eng.md",
    "neuroscience": "neuroscience.md",
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_services(credentials_file: str):
    """Return (docs_service, drive_service)."""
    creds_path = Path(credentials_file).expanduser().resolve()
    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=SCOPES
    )
    docs  = build("docs",  "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return docs, drive


# ── Drive folder helpers ──────────────────────────────────────────────────────

def _get_or_create_folder(drive, name: str, parent_id: str | None = None) -> str:
    """Find or create a Drive folder by name. Returns folder ID."""
    q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        q += f" and '{parent_id}' in parents"

    results = drive.files().list(q=q, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]

    folder = drive.files().create(body=body, fields="id").execute()
    console.print(f"[green]Created Drive folder:[/green] {name}")
    return folder["id"]


def _share_with_user(drive, file_id: str, email: str):
    """Grant a user editor access to a Drive file/folder."""
    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "writer", "emailAddress": email},
            sendNotificationEmail=False,
        ).execute()
        console.print(f"[green]Shared with:[/green] {email}")
    except Exception as e:
        console.print(f"[yellow]Could not share with {email}: {e}[/yellow]")


# ── Doc creation helpers ───────────────────────────────────────────────────────

def _create_doc_in_folder(docs, drive, title: str, folder_id: str) -> str:
    """Create a new Google Doc, move it to folder_id. Returns doc ID."""
    doc = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    # Move from root to target folder
    drive.files().update(
        fileId=doc_id,
        addParents=folder_id,
        removeParents="root",
        fields="id, parents",
    ).execute()
    return doc_id


def _delete_existing_doc(drive, title: str, folder_id: str):
    """Delete any existing doc with the same title in the folder."""
    q = f"name = '{title}' and '{folder_id}' in parents and trashed = false"
    files = drive.files().list(q=q, fields="files(id)").execute().get("files", [])
    for f in files:
        drive.files().delete(fileId=f["id"]).execute()


# ── Markdown → Docs API requests ──────────────────────────────────────────────

_SKIP_PREFIXES = ("# BASE RESUME", "# ─", "# Claude selects", "# ────")


def _build_doc_requests(md_text: str) -> list[dict]:
    """
    Convert a markdown resume string into Google Docs batchUpdate requests.

    Handles:
      ## SECTION HEADER  → HEADING_2
      ### Subsection     → HEADING_3
      - bullet item      → bulleted list paragraph
      **Label:** value   → bold label inline
      plain text         → NORMAL_TEXT
    """
    requests: list[dict] = []
    idx = 1  # Docs body content starts at index 1

    # Strip front-matter comment lines
    clean_lines = [
        line for line in md_text.split("\n")
        if not any(line.startswith(p) for p in _SKIP_PREFIXES)
    ]
    # Trim leading blanks
    while clean_lines and not clean_lines[0].strip():
        clean_lines.pop(0)

    def _insert(text: str):
        nonlocal idx
        requests.append({"insertText": {"location": {"index": idx}, "text": text}})
        idx += len(text)

    def _para_style(start: int, end: int, style: str):
        requests.append({
            "updateParagraphStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "paragraphStyle": {"namedStyleType": style},
                "fields": "namedStyleType",
            }
        })

    def _bold(start: int, end: int):
        requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {"bold": True},
                "fields": "bold",
            }
        })

    for raw_line in clean_lines:
        line = raw_line.rstrip()

        # ── Section header ##
        if line.startswith("## "):
            text = line[3:].strip() + "\n"
            start = idx
            _insert(text)
            _para_style(start, idx, "HEADING_2")

        # ── Subsection header ###
        elif line.startswith("### "):
            text = line[4:].strip() + "\n"
            start = idx
            _insert(text)
            _para_style(start, idx, "HEADING_3")

        # ── Bullet
        elif line.startswith("- ") or line.startswith("* "):
            # Strip ** markers from bullet text
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line[2:].strip())
            text  = plain + "\n"
            start = idx
            _insert(text)
            requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": idx},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
                }
            })

        # ── Empty line
        elif not line.strip():
            _insert("\n")

        # ── Normal text (may contain **bold** spans)
        else:
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            text  = plain + "\n"
            start = idx
            _insert(text)

            # Re-apply bold to all **...** spans
            for m in re.finditer(r"\*\*(.+?)\*\*", line):
                pre       = re.sub(r"\*\*(.+?)\*\*", r"\1", line[: m.start()])
                b_start   = start + len(pre)
                b_end     = b_start + len(m.group(1))
                _bold(b_start, b_end)

    return requests


# ── Public API ────────────────────────────────────────────────────────────────

def setup_base_docs(
    credentials_file: str,
    base_resumes_dir: str = "resumes/base",
    user_email: str | None = None,
) -> tuple[dict[str, str], str]:
    """
    Create the Drive folder structure and 4 base template Google Docs.

    Returns:
        (doc_ids, root_folder_id)
        doc_ids = {"data_science": "<id>", "ml_ai": "<id>", ...}
    """
    docs_svc, drive_svc = _get_services(credentials_file)

    # Folder structure: Job Application Resumes / Base Templates
    root_id = _get_or_create_folder(drive_svc, ROOT_FOLDER_NAME)
    base_id = _get_or_create_folder(drive_svc, BASE_FOLDER_NAME, parent_id=root_id)

    # Share root with user so they can see the docs in their Drive
    if user_email:
        _share_with_user(drive_svc, root_id, user_email)

    base_dir = Path(base_resumes_dir)
    if not base_dir.is_absolute():
        # Try relative to the repo root (parent of src/)
        base_dir = Path(__file__).parent.parent / base_resumes_dir

    doc_ids: dict[str, str] = {}

    for field_key, filename in FIELD_FILES.items():
        md_path = base_dir / filename
        if not md_path.exists():
            console.print(f"[yellow]Skipping {field_key} — not found: {md_path}[/yellow]")
            continue

        md_text = md_path.read_text(encoding="utf-8")
        title   = FIELD_DOC_TITLES[field_key]

        _delete_existing_doc(drive_svc, title, base_id)
        doc_id = _create_doc_in_folder(docs_svc, drive_svc, title, base_id)

        reqs = _build_doc_requests(md_text)
        if reqs:
            docs_svc.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": reqs},
            ).execute()

        doc_ids[field_key] = doc_id
        url = f"https://docs.google.com/document/d/{doc_id}/edit"
        console.print(f"[green]✓[/green] {title}")
        console.print(f"  [dim]{url}[/dim]")

    folder_url = f"https://drive.google.com/drive/folders/{root_id}"
    console.print(f"\n[bold green]Drive folder:[/bold green] {folder_url}")
    return doc_ids, root_id


def create_job_doc(
    tailored_md: str,
    company: str,
    role: str,
    credentials_file: str,
    root_folder_id: str | None = None,
) -> str:
    """
    Create a new Google Doc with tailored resume content for a specific job.
    Returns the Google Doc URL.
    """
    docs_svc, drive_svc = _get_services(credentials_file)

    # Resolve root folder
    if not root_folder_id:
        root_folder_id = _get_or_create_folder(drive_svc, ROOT_FOLDER_NAME)

    # Title: "Company — Role (YYYY-MM-DD)"
    safe_company = re.sub(r"[^\w\s\-]", "", company).strip()
    safe_role    = re.sub(r"[^\w\s\-]", "", role).strip()
    date_str     = datetime.now().strftime("%Y-%m-%d")
    title        = f"{safe_company} — {safe_role} ({date_str})"

    doc_id = _create_doc_in_folder(docs_svc, drive_svc, title, root_folder_id)

    reqs = _build_doc_requests(tailored_md)
    if reqs:
        docs_svc.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": reqs},
        ).execute()

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    console.print(f"[green]Created Google Doc:[/green] {title}")
    console.print(f"  [dim]{url}[/dim]")
    return url
