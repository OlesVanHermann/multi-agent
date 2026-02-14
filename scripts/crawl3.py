#!/usr/bin/env python3
"""
Crawl v3 - Same as crawl2 (no language filter) + 1 second delay between pages.

Identical to crawl2.py except for rate limiting:
- crawl2.py: no delay between downloads (fast, but triggers 429 on some servers)
- crawl3.py: 1 second delay between each page download (slower, avoids 429)

Use crawl3.py when a site returns 429 "Too Many Requests" with crawl2.py.

Usage: python3 crawl3.py <domaine> [--subdomains] [--agent-id=XXX]

Transport: chrome-bridge.py (Extension + Native Messaging Host).
No need for --remote-debugging-port on Chrome.
"""

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse


# =============================================================================
# CHROME BRIDGE IMPORT
# =============================================================================
# Import chrome-bridge.py as a module (handles CDP via Extension bridge HTTP)

_bridge_spec = importlib.util.spec_from_file_location(
    "chrome_bridge", Path(__file__).parent / "chrome-bridge.py"
)
_bridge = importlib.util.module_from_spec(_bridge_spec)
_bridge_spec.loader.exec_module(_bridge)


# =============================================================================
# GLOBAL CONFIGURATION
# =============================================================================

BASE_DIR = Path.home() / "multi-agent"
STUDIES_DIR = BASE_DIR / "studies"
REMOVED_DIR = BASE_DIR / "removed"

# Rate limiting: 1 second between each page download to avoid 429 errors.
# This is THE difference between crawl2.py and crawl3.py.
DELAY_BETWEEN_PAGES = 1

STUDY_DIR = None
HTML_DIR = None
INDEX_DIR = None
FAILED_DIR = None
CONFIG_FILE = None
ROOT_DOMAIN = None
INCLUDE_SUBDOMAINS = False


# =============================================================================
# AGENT IDENTIFICATION
# =============================================================================

AGENT_ID = None


def _detect_agent_id():
    global AGENT_ID
    if AGENT_ID:
        return AGENT_ID
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        AGENT_ID = agent_id
        return agent_id
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        name = result.stdout.strip()
        if name.startswith("ma-agent-"):
            AGENT_ID = name.split("ma-agent-")[1]
        elif name.startswith("agent-"):
            AGENT_ID = name.replace("agent-", "")
    except Exception:
        pass
    return AGENT_ID


# =============================================================================
# URL FILTERING PATTERNS
# =============================================================================

INCLUDE_PATTERNS = []  # Empty = accept all URLs (same as crawl2.py)

EXCLUDE_PATTERNS = [
    r'\?',
    r'#',
    r'/docs/',
    r'/api/',
    r'/cdn-cgi/',
    r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|wav|avi)(\?|$)',
    r'\.(css|js|mjs|json|xml|txt|map|woff|woff2|ttf|eot|otf|rss|atom)(\?|$)',
]


# =============================================================================
# DOMAIN MATCHING
# =============================================================================

def is_same_domain(url_netloc: str, root_domain: str) -> bool:
    if not INCLUDE_SUBDOMAINS:
        return url_netloc == root_domain or url_netloc == f"www.{root_domain}"
    return (url_netloc == root_domain or
            url_netloc.endswith(f".{root_domain}"))


# =============================================================================
# CONFIGURATION
# =============================================================================

def load_config():
    if CONFIG_FILE and CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"include_patterns": INCLUDE_PATTERNS, "exclude_patterns": EXCLUDE_PATTERNS}


# =============================================================================
# SHA-BASED DEDUPLICATION
# =============================================================================

def url_to_sha(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


# =============================================================================
# URL NORMALIZATION
# =============================================================================

def normalize_url(url: str) -> str:
    try:
        url = url.split('#')[0].split('?')[0]
        if url.startswith('http://'):
            url = 'https://' + url[7:]
        if ROOT_DOMAIN:
            parsed = urlparse(url)
            netloc = parsed.netloc
            parts = netloc.split('.')
            if netloc == ROOT_DOMAIN and len(parts) <= 2:
                url = url.replace(f"://{ROOT_DOMAIN}", f"://www.{ROOT_DOMAIN}", 1)
        if url.endswith('/') and url.count('/') > 3:
            url = url.rstrip('/')
        return url
    except (ValueError, Exception):
        return ""


# =============================================================================
# URL FILTERING
# =============================================================================

def should_include_url(url: str, config: dict) -> bool:
    include = config.get("include_patterns", INCLUDE_PATTERNS)
    exclude = config.get("exclude_patterns", EXCLUDE_PATTERNS)
    if include:
        if not any(re.search(p, url, re.IGNORECASE) for p in include):
            return False
    if exclude:
        if any(re.search(p, url, re.IGNORECASE) for p in exclude):
            return False
    return True


# =============================================================================
# HTML LINK EXTRACTION
# =============================================================================

def extract_urls_from_html(html: str, base_url: str, config: dict) -> set:
    urls = set()
    href_pattern = r'href=["\']([^"\']+)["\']'
    parsed_base = urlparse(base_url)

    for match in re.finditer(href_pattern, html, re.IGNORECASE):
        try:
            url = match.group(1).strip()
            if url.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue
            if url.startswith('/'):
                url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
            elif not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)
            url = normalize_url(url)
            if not url:
                continue
            url_domain = urlparse(url).netloc
            if not is_same_domain(url_domain, ROOT_DOMAIN):
                continue
        except (ValueError, Exception):
            continue
        if should_include_url(url, config):
            urls.add(url)

    return urls


# =============================================================================
# CHROME BRIDGE TAB MANAGEMENT
# =============================================================================

def get_or_create_tab():
    """Get or create a dedicated Chrome tab for this agent via the bridge."""
    agent_id = _detect_agent_id()

    if not _bridge.check_chrome_running():
        return None

    # Check existing tab in Redis
    if agent_id:
        tab_id = _bridge.get_agent_tab(agent_id)
        if tab_id:
            if _bridge.validate_target(tab_id):
                return tab_id
            else:
                print(f"⚠ Tab {str(tab_id)[:12]}... obsolete, creation nouveau...", file=sys.stderr)
                _bridge.cleanup_stale_target(agent_id)

    # Create new tab
    tab_id = _bridge.create_tab("about:blank")
    if tab_id and agent_id:
        _bridge.set_agent_tab(agent_id, tab_id)
        print(f"✓ Tab dedie cree pour agent {agent_id}", file=sys.stderr)
    elif not agent_id:
        print(f"⚠ Agent non identifie - tab sans isolation", file=sys.stderr)

    return tab_id


# =============================================================================
# PAGE DOWNLOAD VIA CHROME BRIDGE
# =============================================================================

def download_page(url: str, timeout: int = 15) -> str:
    """Download a single page via the Chrome bridge.

    Uses the CDP class from chrome-bridge.py to navigate and extract HTML.
    Waits for page load completion by polling document.readyState.
    """
    tab_id = get_or_create_tab()
    if not tab_id:
        return ""

    try:
        cdp = _bridge.CDP(tab_id)
        cdp.navigate(url)

        # Wait for page to finish loading (poll readyState)
        for _ in range(timeout):
            time.sleep(1)
            try:
                state = cdp.evaluate("document.readyState")
                if state == "complete":
                    break
            except Exception:
                continue

        # Extra wait for JS rendering (same as original CDP approach)
        time.sleep(2)

        html = cdp.get_html()
        return html or ""
    except Exception as e:
        print(f"    Error: {e}")
        return ""


# =============================================================================
# FILE STATE MANAGEMENT
# =============================================================================

def touch_file(sha: str):
    html_file = HTML_DIR / f"{sha}.html"
    if not html_file.exists():
        html_file.touch()


def is_empty(sha: str) -> bool:
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size == 0


def is_downloaded(sha: str) -> bool:
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size > 100


def is_failed(sha: str) -> bool:
    return (FAILED_DIR / sha).exists()


def mark_failed(sha: str, url: str, reason: str = "download_error"):
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (FAILED_DIR / sha).write_text(f"{url}|{reason}|{timestamp}")
    html_file = HTML_DIR / f"{sha}.html"
    if html_file.exists() and html_file.stat().st_size == 0:
        REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(html_file), str(REMOVED_DIR / f"{timestamp}_{sha}.html"))


# =============================================================================
# DOWNLOAD QUEUE MANAGEMENT
# =============================================================================

def get_empty_files() -> list:
    empty = []
    for html_file in HTML_DIR.glob("*.html"):
        if html_file.stat().st_size == 0:
            sha = html_file.stem
            if is_failed(sha):
                continue
            index_file = INDEX_DIR / sha
            if index_file.exists():
                url = index_file.read_text().strip()
                empty.append((sha, url))
    return empty


def register_url(url: str):
    sha = url_to_sha(url)
    if is_downloaded(sha) or is_failed(sha):
        return False
    touch_file(sha)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_file = INDEX_DIR / sha
    if not index_file.exists():
        index_file.write_text(url)
    return True


# =============================================================================
# BATCH DOWNLOAD (core crawl iteration)
# =============================================================================

def crawl_batch(config: dict) -> tuple:
    empty_files = get_empty_files()
    if not empty_files:
        return 0, 0, 0

    ok = 0
    errors = 0
    new_urls_found = 0

    print(f"\n=== Batch: {len(empty_files)} fichiers vides a telecharger (delay={DELAY_BETWEEN_PAGES}s) ===")

    for i, (sha, url) in enumerate(empty_files, 1):
        if is_failed(sha):
            print(f"[{i}/{len(empty_files)}] SKIP (deja en FAILED): {url[:50]}...")
            continue

        # Rate limiting: wait between downloads to avoid 429
        if i > 1:
            time.sleep(DELAY_BETWEEN_PAGES)

        print(f"[{i}/{len(empty_files)}] {url[:70]}...")

        html = download_page(url)

        if html and len(html) > 500:
            html_lower = html.lower()
            is_error_page = False
            error_reason = None

            if '<title>404' in html_lower or 'page not found' in html_lower or 'not found</title>' in html_lower:
                is_error_page = True
                error_reason = "404_not_found"
            elif '<title>403' in html_lower or 'forbidden</title>' in html_lower or 'access denied' in html_lower:
                is_error_page = True
                error_reason = "403_forbidden"
            elif '<title>500' in html_lower or 'internal server error' in html_lower:
                is_error_page = True
                error_reason = "500_server_error"
            elif '<title>502' in html_lower or 'bad gateway' in html_lower:
                is_error_page = True
                error_reason = "502_bad_gateway"
            elif '<title>503' in html_lower or 'service unavailable' in html_lower:
                is_error_page = True
                error_reason = "503_unavailable"
            elif '<title>429' in html_lower or 'too many requests' in html_lower:
                is_error_page = True
                error_reason = "429_rate_limited"

            if is_error_page:
                mark_failed(sha, url, error_reason)
                errors += 1
                print(f"    FAILED ({error_reason})")
            else:
                html_file = HTML_DIR / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                new_urls = extract_urls_from_html(html, url, config)
                for new_url in new_urls:
                    if register_url(new_url):
                        new_urls_found += 1

                ok += 1
                print(f"    OK ({len(html)//1024}KB, +{len(new_urls)} links)")
        else:
            mark_failed(sha, url, "empty_response")
            errors += 1
            print(f"    FAILED (empty_response)")

    return ok, errors, new_urls_found


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    global STUDY_DIR, HTML_DIR, INDEX_DIR, FAILED_DIR, CONFIG_FILE
    global ROOT_DOMAIN, INCLUDE_SUBDOMAINS, AGENT_ID

    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 1:
        print("Usage: python3 crawl3.py <domaine> [--subdomains] [--agent-id=XXX]")
        print("Exemple: python3 crawl3.py example.com")
        print("\nDifference avec crawl2.py:")
        print(f"  - Delai de {DELAY_BETWEEN_PAGES}s entre chaque telechargement")
        print("  - Evite les erreurs 429 (Too Many Requests)")
        print("  - Detecte aussi les pages 429 comme erreur")
        print("\nTransport: chrome-bridge.py (Extension + Native Messaging Host)")
        return

    domain = args[0]
    INCLUDE_SUBDOMAINS = '--subdomains' in flags

    for flag in flags:
        if flag.startswith('--agent-id='):
            AGENT_ID = flag.split('=', 1)[1]

    ROOT_DOMAIN = domain.removeprefix("www.")

    STUDY_DIR = STUDIES_DIR / domain / "300"
    HTML_DIR = STUDY_DIR / "html"
    INDEX_DIR = STUDY_DIR / "INDEX"
    FAILED_DIR = STUDY_DIR / "FAILED"
    CONFIG_FILE = STUDIES_DIR / domain / "config.json"

    if not STUDY_DIR.exists():
        print(f"Erreur: Etude '{domain}' non trouvee dans {STUDIES_DIR}")
        return

    print(f"Domaine: {domain}")
    print(f"Repertoire: {STUDY_DIR}")
    print(f"Mode: crawl3 (sans filtre langue, delay={DELAY_BETWEEN_PAGES}s)")
    if INCLUDE_SUBDOMAINS:
        print(f"Sous-domaines: actifs (*.{ROOT_DOMAIN})")

    agent_id = _detect_agent_id()
    if agent_id:
        print(f"Agent: {agent_id} (tab isole via Redis)")
    else:
        print(f"⚠ Agent non identifie (utiliser --agent-id=XXX ou AGENT_ID env)")

    tab_id = get_or_create_tab()
    if not tab_id:
        print(f"Chrome bridge not reachable!")
        print()
        print("Verifier que:")
        print("  1. Chrome est lance normalement")
        print("  2. L'extension CDP Bridge est installee et active")
        print("  3. Le native host est installe (./install.sh)")
        print()
        print("  Tester: curl http://127.0.0.1:9222/health")
        return

    print(f"Chrome connected via bridge (tab dedie agent {agent_id or '?'})")

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()

    # =========================================================================
    # PHASE 1: DISCOVERY
    # =========================================================================
    print(f"\nScan des HTML existants...")
    html_files = [f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 100]
    print(f"Fichiers HTML a scanner: {len(html_files)}")

    discovered = 0
    for html_file in html_files:
        try:
            content = html_file.read_text(errors='ignore')
            base_url = f"https://{domain}/"
            if content.startswith("<!-- URL:"):
                base_url = content.split("-->")[0].replace("<!-- URL:", "").strip()
            new_urls = extract_urls_from_html(content, base_url, config)
            for url in new_urls:
                if register_url(url):
                    discovered += 1
        except Exception:
            pass

    print(f"Nouvelles URLs decouvertes: {discovered}")

    total_files = len(list(HTML_DIR.glob("*.html")))
    empty_files = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
    print(f"\nTotal fichiers: {total_files}")
    print(f"Fichiers vides (a telecharger): {empty_files}")

    # =========================================================================
    # PHASE 2: CRAWL LOOP
    # =========================================================================
    iteration = 0
    total_ok = 0
    total_errors = 0

    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print(f"{'='*60}")

        ok, errors, new_urls = crawl_batch(config)
        total_ok += ok
        total_errors += errors

        print(f"\nResultat iteration {iteration}:")
        print(f"  Telecharges: {ok}")
        print(f"  Erreurs: {errors}")
        print(f"  Nouvelles URLs decouvertes: {new_urls}")

        remaining = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
        print(f"  Fichiers vides restants: {remaining}")

        if remaining == 0:
            print("\nPlus de fichiers vides, crawl termine!")
            break

        if ok == 0 and errors == 0:
            print("\nAucun progres, arret.")
            break

    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"CRAWL TERMINE")
    print(f"{'='*60}")
    print(f"Total telecharges: {total_ok}")
    print(f"Total erreurs: {total_errors}")
    final_count = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 0])
    print(f"Fichiers HTML valides: {final_count}")


if __name__ == "__main__":
    main()
