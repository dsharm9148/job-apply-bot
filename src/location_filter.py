"""
Filters jobs by approved locations.
Returns True if the job location is in the approved list, False otherwise.
"""

import re
from rich.console import Console

console = Console()

# ─── APPROVED LOCATIONS ───────────────────────────────────────────────────────
# Edit this list to add/remove cities.

APPROVED_LOCATIONS = [
    # California
    "san diego",
    "la jolla",
    "chula vista",
    "carlsbad",
    "san francisco",
    "sf",
    "bay area",
    "silicon valley",
    "san jose",
    "santa clara",
    "mountain view",
    "palo alto",
    "menlo park",
    "redwood city",
    "sunnyvale",
    "cupertino",
    "los angeles",
    "la",
    "santa monica",
    "culver city",
    "west hollywood",
    "burbank",
    "pasadena",
    "irvine",
    "orange county",
    # Florida
    "miami",
    "miami beach",
    "fort lauderdale",
    "boca raton",
    "tampa",
    "st. petersburg",
    "clearwater",
    # Texas
    "austin",
    # Washington
    "seattle",
    "bellevue",
    "redmond",
    "kirkland",
    # Colorado
    "denver",
    "boulder",
    "colorado springs",
    # New York
    "new york",
    "nyc",
    "new york city",
    "brooklyn",
    "manhattan",
    # Massachusetts
    "boston",
    "cambridge",
    "somerville",
    # DC
    "washington, dc",
    "washington dc",
    "dc",
    "arlington",
    "bethesda",
    "northern virginia",
    "nova",
    # Illinois
    "chicago",
    # Georgia
    "atlanta",
    # North Carolina
    "raleigh",
    "durham",
    "chapel hill",
    "research triangle",
    # Oregon
    "portland",
    # Utah
    "salt lake city",
    "slc",
    "provo",
    # Remote
    "remote",
    "hybrid",
    "anywhere",
    "united states",
    "us remote",
    "nationwide",
]

# States that are broadly approved (catches "CA", "New York, NY", etc.)
APPROVED_STATES = [
    "ca",
    "california",
    "wa",
    "washington",
    "co",
    "colorado",
    "tx",  # only Austin — but state-level match is allowed, JD usually says city
    "ny",
    "new york",
    "ma",
    "massachusetts",
    "fl",
    "florida",
    "il",
    "illinois",
    "or",
    "oregon",
    "ut",
    "utah",
    "nc",  # Research Triangle area
    "ga",  # Atlanta
]


def is_approved_location(location: str) -> tuple[bool, str]:
    """
    Check if a job location is in the approved list.
    Returns (approved: bool, reason: str).
    """
    if not location or location.strip() == "":
        # Unknown location — allow with a warning
        return True, "Location unknown — allowing"

    loc_lower = location.lower().strip()

    # Direct match against approved cities
    for approved in APPROVED_LOCATIONS:
        if approved in loc_lower:
            return True, f"Matched: {approved}"

    # State-level match (e.g. "San Francisco, CA" → matches "ca")
    for state in APPROVED_STATES:
        # Match state abbreviation at end: ", CA" or " CA" or "(CA)"
        if re.search(r'[\s,\(]' + re.escape(state) + r'[\s,\)]*$', loc_lower):
            return True, f"State match: {state.upper()}"
        # Full state name anywhere
        if re.search(r'\b' + re.escape(state) + r'\b', loc_lower):
            return True, f"State match: {state}"

    return False, f"Not in approved locations: '{location}'"


def filter_location(location: str, company: str = "", role: str = "") -> bool:
    """
    Main filter function. Logs result and returns bool.
    True = approved, False = skip.
    """
    approved, reason = is_approved_location(location)

    if approved:
        console.print(f"[green]✓ Location approved:[/green] {location} ({reason})")
    else:
        console.print(f"[yellow]✗ Location filtered out:[/yellow] {location}")
        if company and role:
            console.print(f"  [dim]Skipping {company} — {role}[/dim]")

    return approved
