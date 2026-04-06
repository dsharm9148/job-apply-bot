"""
Scrapes job descriptions from ATS platforms and career pages.
Supports: Lever, Greenhouse, Workday, Indeed, LinkedIn, and generic pages.
"""

import re
import requests
from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36'
}


def detect_platform(url: str) -> str:
    if 'lever.co' in url:       return 'lever'
    if 'greenhouse.io' in url:  return 'greenhouse'
    if 'myworkdayjobs' in url:  return 'workday'
    if 'indeed.com' in url:     return 'indeed'
    if 'linkedin.com' in url:   return 'linkedin'
    if 'smartrecruiters' in url: return 'smartrecruiters'
    if 'jobvite.com' in url:    return 'jobvite'
    return 'generic'


def normalize_url(url: str, platform: str) -> str:
    """Strip /apply suffix etc. to get the description page."""
    if platform == 'lever':
        # https://jobs.lever.co/company/uuid/apply → remove /apply
        url = re.sub(r'/apply$', '', url.rstrip('/'))
    return url


def scrape_lever(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # Lever structure: .posting-headline + .section-wrapper divs
    parts = []
    title = soup.find('h2')
    if title:
        parts.append(title.get_text(strip=True))

    for section in soup.select('.section-wrapper, .posting-requirements, .posting-content'):
        parts.append(section.get_text(separator='\n', strip=True))

    return '\n\n'.join(parts) if parts else soup.get_text(separator='\n', strip=True)


def scrape_greenhouse(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    parts = []
    for sel in ['#content', '.job-post', '#app_body', 'article']:
        el = soup.select_one(sel)
        if el:
            parts.append(el.get_text(separator='\n', strip=True))
            break

    return '\n\n'.join(parts) if parts else soup.get_text(separator='\n', strip=True)


def scrape_generic(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # Remove noise
    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
        tag.decompose()

    # Try common job content containers
    for sel in ['main', 'article', '.job-description', '#job-description',
                '.description', '.job-details', '.content', '#content']:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(separator='\n', strip=True)
            if len(text) > 300:
                return text

    return soup.get_text(separator='\n', strip=True)


def scrape_job_description(url: str) -> str | None:
    """
    Main entry point. Returns cleaned job description text, or None if failed.
    """
    if not url or url.strip().lower() in ('', 'apply', 'n/a'):
        return None

    platform = detect_platform(url)
    url = normalize_url(url, platform)

    console.print(f"[dim]Scraping job description ({platform}): {url}[/dim]")

    try:
        if platform == 'lever':
            text = scrape_lever(url)
        elif platform == 'greenhouse':
            text = scrape_greenhouse(url)
        else:
            text = scrape_generic(url)

        # Clean up
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        text = text.strip()

        if len(text) < 200:
            console.print("[yellow]Warning: scraped text seems too short — job page may require login[/yellow]")
            return None

        console.print(f"[green]✓ Scraped {len(text)} chars[/green]")
        return text

    except Exception as e:
        console.print(f"[red]Scrape failed:[/red] {e}")
        return None
