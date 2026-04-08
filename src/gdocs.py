"""
Google Docs / Drive integration for resume management.

Strategy:
  - Base docs: copy mega resume → delete irrelevant entries per field (preserves ALL formatting)
  - Per-job docs: copy the field's base template doc → rename for the job

Setup:
  python main.py setup-gdocs --email diyasharma5030@gmail.com
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

ROOT_FOLDER_NAME  = "Job Application Resumes"
BASE_FOLDER_NAME  = "Base Templates"
MEGA_DOC_ID       = "1jHbm3J8mxNUEx8JoJj7v4k52UcDbcZpngLnPyaN5px4"

# OAuth paths (service accounts have zero Drive storage quota)
_OAUTH_CLIENT_FILE = "~/job-apply-bot/gdocs_oauth_client.json"
_OAUTH_TOKEN_FILE  = "~/job-apply-bot/gdocs_token.json"

FIELD_DOC_TITLES = {
    "data_science": "Base Resume — Data Science",
    "ml_ai":        "Base Resume — ML / AI",
    "software_eng": "Base Resume — Software Engineering",
    "neuroscience": "Base Resume — Neuroscience Research",
}

# ── What to DELETE from the mega resume for each field base doc ───────────────
# Keys are matched case-insensitively against paragraph text.
# "entries" = individual experience/project blocks (ends at next entry/section header)
# "sections" = entire top-level sections (ends at next section header)
FIELD_DELETIONS: dict[str, dict[str, list[str]]] = {
    "data_science": {
        "entries":  ["Johns Hopkins University Applied Physics",
                     "Surgical Arm, GT Medical Robotics",
                     "Beyond Barca Project",
                     "Travel Photography Website"],
        "sections": ["TEACHING", "STUDY ABROAD", "ADDITIONAL"],
    },
    "ml_ai": {
        "entries":  ["Johns Hopkins University Applied Physics",
                     "Beyond Barca Project",
                     "Travel Photography Website",
                     "CS 2340 - Scrum Master"],
        "sections": ["TEACHING", "STUDY ABROAD", "ADDITIONAL"],
    },
    "software_eng": {
        "entries":  [],   # keep everything — SWE needs breadth
        "sections": ["TEACHING", "STUDY ABROAD", "ADDITIONAL"],
    },
    "neuroscience": {
        "entries":  ["Johns Hopkins University Applied Physics",
                     "Beyond Barca Project",
                     "Travel Photography Website",
                     "CS 2340 - Scrum Master"],
        "sections": ["TEACHING", "STUDY ABROAD", "ADDITIONAL"],
    },
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_services(credentials_file: str):
    """
    Return (docs_service, drive_service).
    Uses OAuth user credentials so docs are owned by the user (not the service account).
    """
    oauth_client = Path(_OAUTH_CLIENT_FILE).expanduser()
    oauth_token  = Path(_OAUTH_TOKEN_FILE).expanduser()

    if oauth_client.exists():
        from google.oauth2.credentials import Credentials as OAuthCreds
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        creds = None
        if oauth_token.exists():
            creds = OAuthCreds.from_authorized_user_file(str(oauth_token), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                console.print("[yellow]Opening browser for Google Drive authorization...[/yellow]")
                flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client), SCOPES)
                creds = flow.run_local_server(port=0)
            with open(str(oauth_token), "w") as f:
                f.write(creds.to_json())
    else:
        creds_path = Path(credentials_file).expanduser().resolve()
        creds = service_account.Credentials.from_service_account_file(
            str(creds_path), scopes=SCOPES
        )

    docs  = build("docs",  "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return docs, drive


# ── Drive helpers ─────────────────────────────────────────────────────────────

def _get_or_create_folder(drive, name: str, parent_id: str | None = None) -> str:
    q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    results = drive.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    folder = drive.files().create(body=body, fields="id").execute()
    console.print(f"[green]Created Drive folder:[/green] {name}")
    return folder["id"]


def _delete_existing(drive, name: str, folder_id: str):
    q = f"name = '{name}' and '{folder_id}' in parents and trashed = false"
    for f in drive.files().list(q=q, fields="files(id)").execute().get("files", []):
        drive.files().delete(fileId=f["id"]).execute()


def _share_with_user(drive, file_id: str, email: str):
    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "writer", "emailAddress": email},
            sendNotificationEmail=False,
        ).execute()
        console.print(f"[green]Shared with:[/green] {email}")
    except Exception as e:
        console.print(f"[yellow]Could not share with {email}: {e}[/yellow]")


# ── Doc block-deletion logic ──────────────────────────────────────────────────

def _get_paragraphs(doc: dict) -> list[dict]:
    """Return flat list of paragraph dicts with start, end, text, type."""
    result = []
    for elem in doc["body"]["content"]:
        para = elem.get("paragraph")
        if not para:
            continue
        text = "".join(
            r.get("textRun", {}).get("content", "")
            for r in para.get("elements", [])
        ).rstrip("\n")

        stripped = text.strip()
        if stripped.isupper() and len(stripped) > 2 and "\t" not in stripped:
            ptype = "section_header"
        elif "\t" in text:
            ptype = "entry_header"
        else:
            ptype = "content"

        result.append({
            "start": elem["startIndex"],
            "end":   elem["endIndex"],
            "text":  text,
            "type":  ptype,
        })
    return result


def _find_deletion_ranges(
    paragraphs: list[dict],
    entry_keywords: list[str],
    section_keywords: list[str],
    doc_end_index: int = 0,
) -> list[tuple[int, int]]:
    """
    Returns a sorted, merged list of (start, end) character ranges to delete.

    entry_keywords  — keyword present in an entry_header paragraph;
                      deletes that paragraph through the next entry/section header.
    section_keywords — keyword present in a section_header paragraph;
                       deletes that paragraph through the next section_header.
    """
    n = len(paragraphs)
    ranges: list[tuple[int, int]] = []

    def next_boundary(from_i: int, boundary_types: set[str]) -> int:
        for j in range(from_i + 1, n):
            if paragraphs[j]["type"] in boundary_types:
                return j
        return n

    # ── Section deletions ─────────────────────────────────────────────────────
    for kw in section_keywords:
        for i, p in enumerate(paragraphs):
            if p["type"] == "section_header" and kw.lower() in p["text"].lower():
                end_i = next_boundary(i, {"section_header"})
                end_char = paragraphs[end_i]["start"] if end_i < n else paragraphs[-1]["end"]
                ranges.append((p["start"], end_char))
                break

    # ── Entry deletions ───────────────────────────────────────────────────────
    for kw in entry_keywords:
        for i, p in enumerate(paragraphs):
            if kw.lower() in p["text"].lower():
                end_i = next_boundary(i, {"section_header", "entry_header"})
                end_char = paragraphs[end_i]["start"] if end_i < n else paragraphs[-1]["end"]
                ranges.append((p["start"], end_char))
                break

    if not ranges:
        return []

    # Cap end indices — Google Docs won't let you delete the final mandatory newline
    max_end = (doc_end_index - 1) if doc_end_index > 1 else (paragraphs[-1]["end"] - 1)
    ranges = [(s, min(e, max_end)) for s, e in ranges if s < max_end]

    # Merge overlapping / adjacent ranges, sort descending (delete back-to-front)
    ranges.sort()
    merged: list[tuple[int, int]] = [ranges[0]]
    for s, e in ranges[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    merged.sort(reverse=True)   # reverse so deletions don't shift later indices
    return merged


def _delete_ranges(docs, doc_id: str, ranges: list[tuple[int, int]]):
    """Delete character ranges from a doc (must be in reverse order)."""
    if not ranges:
        return
    requests = [
        {"deleteContentRange": {"range": {"startIndex": s, "endIndex": e}}}
        for s, e in ranges
    ]
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()


# ── Public API ────────────────────────────────────────────────────────────────

def setup_base_docs(
    credentials_file: str,
    user_email: str | None = None,
) -> tuple[dict[str, str], str]:
    """
    Copy the mega resume 4 times (one per field), delete irrelevant blocks in
    each copy.  Returns (doc_ids, root_folder_id).
    """
    docs_svc, drive_svc = _get_services(credentials_file)

    root_id = _get_or_create_folder(drive_svc, ROOT_FOLDER_NAME)
    base_id = _get_or_create_folder(drive_svc, BASE_FOLDER_NAME, parent_id=root_id)

    if user_email:
        _share_with_user(drive_svc, root_id, user_email)

    doc_ids: dict[str, str] = {}

    for field_key, deletions in FIELD_DELETIONS.items():
        title = FIELD_DOC_TITLES[field_key]
        _delete_existing(drive_svc, title, base_id)

        # ── 1. Copy mega resume (preserves every formatting detail) ────────────
        copied = drive_svc.files().copy(
            fileId=MEGA_DOC_ID,
            body={"name": title, "parents": [base_id]},
        ).execute()
        doc_id = copied["id"]

        # ── 2. Parse paragraphs and delete irrelevant blocks ───────────────────
        doc        = docs_svc.documents().get(documentId=doc_id).execute()
        paragraphs = _get_paragraphs(doc)
        doc_end    = doc["body"].get("endIndex", 0)
        ranges     = _find_deletion_ranges(
            paragraphs,
            entry_keywords   = deletions["entries"],
            section_keywords = deletions["sections"],
            doc_end_index    = doc_end,
        )
        _delete_ranges(docs_svc, doc_id, ranges)

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
    field_key: str | None = None,
    base_doc_ids: dict | None = None,
) -> str:
    """
    Copy the base template doc for this field and name it for the job.
    Returns the Google Doc URL.

    Falls back to building from markdown if base_doc_ids not configured.
    """
    docs_svc, drive_svc = _get_services(credentials_file)

    if not root_folder_id:
        root_folder_id = _get_or_create_folder(drive_svc, ROOT_FOLDER_NAME)

    safe_company = re.sub(r"[^\w\s\-]", "", company).strip()
    safe_role    = re.sub(r"[^\w\s\-]", "", role).strip()
    date_str     = datetime.now().strftime("%Y-%m-%d")
    title        = f"{safe_company} — {safe_role} ({date_str})"

    base_doc_id = (base_doc_ids or {}).get(field_key or "") if base_doc_ids else None

    if base_doc_id:
        # Copy base template — preserves all formatting
        copied = drive_svc.files().copy(
            fileId=base_doc_id,
            body={"name": title, "parents": [root_folder_id]},
        ).execute()
        doc_id = copied["id"]
    else:
        # Fallback: create from markdown
        doc_id = _create_doc_from_markdown(docs_svc, drive_svc, title, tailored_md, root_folder_id)

    url = f"https://docs.google.com/document/d/{doc_id}/edit"
    console.print(f"[green]Created Google Doc:[/green] {title}")
    console.print(f"  [dim]{url}[/dim]")
    return url


# ── Markdown fallback (used only if base_doc_ids not configured) ──────────────

def _create_doc_from_markdown(docs_svc, drive_svc, title: str, md: str, folder_id: str) -> str:
    doc = docs_svc.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    drive_svc.files().update(
        fileId=doc_id, addParents=folder_id, removeParents="root", fields="id"
    ).execute()
    reqs = _build_md_requests(md)
    if reqs:
        docs_svc.documents().batchUpdate(documentId=doc_id, body={"requests": reqs}).execute()
    return doc_id


def _build_md_requests(md_text: str) -> list[dict]:
    requests: list[dict] = []
    idx = 1
    skip = ("# BASE RESUME", "# ─", "# Claude selects", "# ────")
    lines = [l for l in md_text.split("\n") if not any(l.startswith(p) for p in skip)]
    while lines and not lines[0].strip():
        lines.pop(0)

    def ins(text):
        nonlocal idx
        requests.append({"insertText": {"location": {"index": idx}, "text": text}})
        idx += len(text)

    def ps(s, e, style):
        requests.append({"updateParagraphStyle": {"range": {"startIndex": s, "endIndex": e},
            "paragraphStyle": {"namedStyleType": style}, "fields": "namedStyleType"}})

    def bold(s, e):
        requests.append({"updateTextStyle": {"range": {"startIndex": s, "endIndex": e},
            "textStyle": {"bold": True}, "fields": "bold"}})

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## "):
            t = line[3:].strip() + "\n"; s = idx; ins(t); ps(s, idx, "HEADING_2")
        elif line.startswith("### "):
            t = line[4:].strip() + "\n"; s = idx; ins(t); ps(s, idx, "HEADING_3")
        elif line.startswith("- ") or line.startswith("* "):
            t = re.sub(r"\*\*(.+?)\*\*", r"\1", line[2:].strip()) + "\n"
            s = idx; ins(t)
            requests.append({"createParagraphBullets": {"range": {"startIndex": s, "endIndex": idx},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"}})
        elif not line.strip():
            ins("\n")
        else:
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            s = idx; ins(plain + "\n")
            for m in re.finditer(r"\*\*(.+?)\*\*", line):
                pre = re.sub(r"\*\*(.+?)\*\*", r"\1", line[:m.start()])
                bold(s + len(pre), s + len(pre) + len(m.group(1)))

    return requests
