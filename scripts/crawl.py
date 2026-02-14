#!/usr/bin/env python3
"""
crawl.py -- Website Crawler via Chrome Extension Bridge

Supports multi-domain round-robin crawling to avoid rate limiting.

Usage:
    python3 crawl.py <domain>                              # Single domain
    python3 crawl.py <d1> <d2> <d3> ... [--agent-id=XXX]  # Multi-domain (max 10)

Multi-domain mode downloads one page from each domain in turn (round-robin),
providing natural inter-request delay per site without artificial sleep.

KEY DIFFERENCE FROM crawl2.py:
    crawl.py has INCLUDE_PATTERNS = [r'/en/', r'/fr/'] -- only crawl
    English and French pages. Use crawl2.py for sites without language prefixes.

Transport: chrome-bridge.py (Extension + Native Messaging Host).
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

_bridge_spec = importlib.util.spec_from_file_location(
    "chrome_bridge", Path(__file__).parent / "chrome-bridge.py"
)
_bridge = importlib.util.module_from_spec(_bridge_spec)
_bridge_spec.loader.exec_module(_bridge)


# =============================================================================
# CONSTANTS
# =============================================================================

BASE_DIR = Path.home() / "multi-agent"
STUDIES_DIR = BASE_DIR / "studies"
REMOVED_DIR = BASE_DIR / "removed"

# KEY DIFFERENCE: language filter active
INCLUDE_PATTERNS = [
    r'/en/',   # Pages anglaises
    r'/fr/',   # Pages francaises
]

EXCLUDE_PATTERNS = [
    r'\?',
    r'#',
    r'/docs/',
    r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|wav|avi)(\?|$)',
    r'\.(css|js|mjs|json|xml|txt|map|woff|woff2|ttf|eot|otf|rss|atom)(\?|$)',
]


# =============================================================================
# UTILITIES
# =============================================================================

def url_to_sha(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def detect_agent_id(forced_id=None):
    """Detect agent ID from flag, env, or tmux session."""
    if forced_id:
        return forced_id
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        return agent_id
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        name = result.stdout.strip()
        if name.startswith("ma-agent-"):
            return name.split("ma-agent-")[1]
        elif name.startswith("agent-"):
            return name.replace("agent-", "")
    except Exception:
        pass
    return None


# =============================================================================
# DOMAIN CRAWLER CLASS
# =============================================================================

class DomainCrawler:
    """Encapsulates all crawl state for a single domain."""

    # Extra sleep after page load, decreases with more domains (round-robin = natural delay)
    SLEEP_BY_COUNT = {1: 1.0, 2: 0.5, 3: 0.24, 4: 0.12, 5: 0.06, 6: 0.02}

    def __init__(self, domain, include_subdomains=False, agent_suffix="", extra_sleep=0.5):
        self.domain = domain
        self.root_domain = domain.removeprefix("www.")
        self.include_subdomains = include_subdomains
        self.agent_suffix = agent_suffix
        self.extra_sleep = extra_sleep

        # Directories
        self.study_dir = STUDIES_DIR / domain / "300"
        self.html_dir = self.study_dir / "html"
        self.index_dir = self.study_dir / "INDEX"
        self.failed_dir = self.study_dir / "FAILED"
        self.config_file = STUDIES_DIR / domain / "config.json"

        # Config
        self.config = self._load_config()

        # Chrome state
        self.tab_id = None
        self.cdp = None

        # Queue: list of (sha, url) + set for O(1) dedup
        self.pending = []
        self.pending_shas = set()

        # Counters
        self.total_ok = 0
        self.total_errors = 0
        self.total_new_urls = 0
        self.active = True

    def _load_config(self):
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {"include_patterns": INCLUDE_PATTERNS, "exclude_patterns": EXCLUDE_PATTERNS}

    # =========================================================================
    # SETUP
    # =========================================================================

    def validate(self) -> bool:
        if not self.study_dir.exists():
            print(f"  SKIP {self.domain}: etude non trouvee dans {STUDIES_DIR}")
            self.active = False
            return False
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        return True

    def setup_tab(self, base_agent_id) -> bool:
        agent_key = f"{base_agent_id}{self.agent_suffix}" if base_agent_id else None

        if agent_key:
            tab_id = _bridge.get_agent_tab(agent_key)
            if tab_id and _bridge.validate_target(tab_id):
                self.tab_id = tab_id
                self.cdp = _bridge.CDP(tab_id)
                return True
            elif tab_id:
                _bridge.cleanup_stale_target(agent_key)

        tab_id = _bridge.create_tab("about:blank")
        if tab_id:
            self.tab_id = tab_id
            self.cdp = _bridge.CDP(tab_id)
            if agent_key:
                _bridge.set_agent_tab(agent_key, tab_id)
            return True

        self.active = False
        return False

    # =========================================================================
    # URL HELPERS
    # =========================================================================

    def normalize_url(self, url: str) -> str:
        try:
            url = url.split('#')[0].split('?')[0]
            if url.startswith('http://'):
                url = 'https://' + url[7:]
            parsed = urlparse(url)
            netloc = parsed.netloc
            parts = netloc.split('.')
            if netloc == self.root_domain and len(parts) <= 2:
                url = url.replace(f"://{self.root_domain}", f"://www.{self.root_domain}", 1)
            if url.endswith('/') and url.count('/') > 3:
                url = url.rstrip('/')
            return url
        except (ValueError, Exception):
            return ""

    def is_same_domain(self, url_netloc: str) -> bool:
        if not self.include_subdomains:
            return url_netloc == self.root_domain or url_netloc == f"www.{self.root_domain}"
        return url_netloc == self.root_domain or url_netloc.endswith(f".{self.root_domain}")

    def should_include_url(self, url: str) -> bool:
        include = self.config.get("include_patterns", INCLUDE_PATTERNS)
        exclude = self.config.get("exclude_patterns", EXCLUDE_PATTERNS)
        if include:
            if not any(re.search(p, url, re.IGNORECASE) for p in include):
                return False
        if exclude:
            if any(re.search(p, url, re.IGNORECASE) for p in exclude):
                return False
        return True

    def extract_urls_from_html(self, html: str, base_url: str) -> set:
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
                url = self.normalize_url(url)
                if not url:
                    continue
                url_domain = urlparse(url).netloc
                if not self.is_same_domain(url_domain):
                    continue
            except (ValueError, Exception):
                continue
            if self.should_include_url(url):
                urls.add(url)
        return urls

    # =========================================================================
    # FILE STATE
    # =========================================================================

    def touch_file(self, sha: str):
        html_file = self.html_dir / f"{sha}.html"
        if not html_file.exists():
            html_file.touch()

    def is_downloaded(self, sha: str) -> bool:
        html_file = self.html_dir / f"{sha}.html"
        return html_file.exists() and html_file.stat().st_size > 100

    def is_failed(self, sha: str) -> bool:
        return (self.failed_dir / sha).exists()

    def mark_failed(self, sha: str, url: str, reason: str = "download_error"):
        self.failed_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        (self.failed_dir / sha).write_text(f"{url}|{reason}|{timestamp}")
        html_file = self.html_dir / f"{sha}.html"
        if html_file.exists() and html_file.stat().st_size == 0:
            REMOVED_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(str(html_file), str(REMOVED_DIR / f"{timestamp}_{sha}.html"))

    def register_url(self, url: str) -> bool:
        sha = url_to_sha(url)
        if self.is_downloaded(sha) or self.is_failed(sha):
            return False
        self.touch_file(sha)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        index_file = self.index_dir / sha
        if not index_file.exists():
            index_file.write_text(url)
            return True
        return False

    def register_and_queue(self, url: str) -> bool:
        sha = url_to_sha(url)
        if self.is_downloaded(sha) or self.is_failed(sha) or sha in self.pending_shas:
            return False
        self.touch_file(sha)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        index_file = self.index_dir / sha
        if not index_file.exists():
            index_file.write_text(url)
        self.pending.append((sha, url))
        self.pending_shas.add(sha)
        return True

    # =========================================================================
    # QUEUE MANAGEMENT
    # =========================================================================

    def refresh_pending(self):
        self.pending = []
        self.pending_shas = set()
        for html_file in self.html_dir.glob("*.html"):
            if html_file.stat().st_size == 0:
                sha = html_file.stem
                if self.is_failed(sha):
                    continue
                index_file = self.index_dir / sha
                if index_file.exists():
                    url = index_file.read_text().strip()
                    self.pending.append((sha, url))
                    self.pending_shas.add(sha)

    def has_pending(self) -> bool:
        return self.active and len(self.pending) > 0

    # =========================================================================
    # DISCOVERY
    # =========================================================================

    def discover(self) -> int:
        html_files = [f for f in self.html_dir.glob("*.html") if f.stat().st_size > 100]
        discovered = 0
        for html_file in html_files:
            try:
                content = html_file.read_text(errors='ignore')
                base_url = self.config.get("base_url", f"https://{self.domain}/")
                if content.startswith("<!-- URL:"):
                    base_url = content.split("-->")[0].replace("<!-- URL:", "").strip()
                new_urls = self.extract_urls_from_html(content, base_url)
                for url in new_urls:
                    if self.register_url(url):
                        discovered += 1
            except Exception:
                pass
        return discovered

    # =========================================================================
    # CORE: PROCESS ONE PAGE
    # =========================================================================

    def process_one(self) -> bool:
        if not self.pending:
            return False

        sha, url = self.pending.pop(0)
        self.pending_shas.discard(sha)

        if self.is_failed(sha) or self.is_downloaded(sha):
            return True

        html = ""
        try:
            self.cdp.navigate(url)
            for _ in range(30):
                time.sleep(0.3)
                try:
                    state = self.cdp.evaluate("document.readyState")
                    if state == "complete":
                        break
                except Exception:
                    continue
            if self.extra_sleep > 0:
                time.sleep(self.extra_sleep)
            html = self.cdp.get_html() or ""
        except Exception as e:
            print(f"  [{self.domain}] Error: {e}")
            html = ""

        if html and len(html) > 500:
            html_lower = html.lower()
            _head_m = re.search(r'<head[^>]*>(.*?)</head>', html_lower, re.DOTALL)
            _head_s = _head_m.group(1) if _head_m else html_lower[:5000]
            _title_m = re.search(r'<title[^>]*>(.*?)</title>', _head_s, re.DOTALL)
            _page_title = _title_m.group(1).strip() if _title_m else ''

            error_reason = None
            for code, patterns in [
                ("404_not_found", ['404', 'not found']),
                ("403_forbidden", ['403', 'forbidden']),
                ("500_server_error", ['500', 'internal server error']),
                ("502_bad_gateway", ['502', 'bad gateway']),
                ("503_unavailable", ['503', 'service unavailable']),
            ]:
                if any(p in _page_title for p in patterns):
                    error_reason = code
                    break

            if error_reason:
                self.mark_failed(sha, url, error_reason)
                self.total_errors += 1
                print(f"  [{self.domain}] FAILED ({error_reason}): {url[:60]}")
            else:
                html_file = self.html_dir / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                new_urls = self.extract_urls_from_html(html, url)
                new_count = 0
                for new_url in new_urls:
                    if self.register_and_queue(new_url):
                        new_count += 1
                        self.total_new_urls += 1

                self.total_ok += 1
                print(f"  [{self.domain}] OK ({len(html)//1024}KB, +{len(new_urls)} links): {url[:60]}")
        else:
            self.mark_failed(sha, url, "empty_response")
            self.total_errors += 1
            print(f"  [{self.domain}] FAILED (empty): {url[:60]}")

        return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 1:
        print("Usage: python3 crawl.py <domain> [<domain2> ... <domain10>] [options]")
        print()
        print("Single domain:  python3 crawl.py example.com")
        print("Multi-domain:   python3 crawl.py d1.com d2.com d3.com")
        print("                (round-robin, max 10 domains, no sleep needed)")
        print()
        print("Options:")
        print("  --subdomains      Include subdomains (docs.X, help.X, etc.)")
        print("  --agent-id=XXX    Force agent ID (default: auto-detect tmux/env)")
        print()
        print("Mode: crawl (language filter: /en/ /fr/)")
        print("Transport: chrome-bridge.py (Extension + Native Messaging Host)")
        print()
        print("Etudes disponibles:")
        for d in STUDIES_DIR.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                print(f"  - {d.name}")
        return

    domains = args[:10]
    include_subdomains = '--subdomains' in flags
    forced_agent_id = None
    for flag in flags:
        if flag.startswith('--agent-id='):
            forced_agent_id = flag.split('=', 1)[1]

    agent_id = detect_agent_id(forced_agent_id)

    if not _bridge.check_chrome_running():
        print("Chrome bridge not reachable!")
        print("  Tester: curl http://127.0.0.1:9222/health")
        return

    # Create crawlers
    extra_sleep = DomainCrawler.SLEEP_BY_COUNT.get(len(domains), 0.0)
    print(f"Initialisation ({len(domains)} domaine(s), sleep={extra_sleep}s)...")
    crawlers = []
    for i, domain in enumerate(domains):
        suffix = f"_{i}" if len(domains) > 1 else ""
        c = DomainCrawler(domain, include_subdomains, suffix, extra_sleep)
        if not c.validate():
            continue
        if c.setup_tab(agent_id):
            crawlers.append(c)
            print(f"  [{domain}] Ready (tab={str(c.tab_id)[:12]}...)")
        else:
            print(f"  [{domain}] SKIP: failed to create Chrome tab")

    if not crawlers:
        print("No valid domains to crawl.")
        return

    multi = len(crawlers) > 1
    mode = f"round-robin ({len(crawlers)} domaines, filtre /en/ /fr/)" if multi else "single (filtre /en/ /fr/)"
    print(f"\nMode: {mode}")
    print(f"Agent: {agent_id or '?'}")

    # =========================================================================
    # PHASE 1: DISCOVERY
    # =========================================================================
    print(f"\n--- Phase 1: Discovery ---")
    for c in crawlers:
        discovered = c.discover()
        c.refresh_pending()
        total = len(list(c.html_dir.glob("*.html")))
        print(f"  [{c.domain}] {total} fichiers, {len(c.pending)} a telecharger, +{discovered} nouvelles URLs")

    # =========================================================================
    # PHASE 2: ROUND-ROBIN CRAWL
    # =========================================================================
    print(f"\n--- Phase 2: Crawl ---")
    page_count = 0

    while any(c.has_pending() for c in crawlers):
        progress = False

        for c in crawlers:
            if c.has_pending():
                if c.process_one():
                    progress = True
                    page_count += 1

        if page_count % 50 == 0 and page_count > 0:
            total_pending = sum(len(c.pending) for c in crawlers)
            active = sum(1 for c in crawlers if c.has_pending())
            print(f"\n--- Progress: {page_count} pages, {active} domaines actifs, {total_pending} en attente ---")

        if not progress:
            for c in crawlers:
                if c.active:
                    c.refresh_pending()
            if not any(c.has_pending() for c in crawlers):
                break

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"CRAWL TERMINE")
    print(f"{'='*60}")
    for c in crawlers:
        final = len([f for f in c.html_dir.glob("*.html") if f.stat().st_size > 0])
        print(f"  [{c.domain}] ok={c.total_ok} erreurs={c.total_errors} HTML valides={final}")
    total_ok = sum(c.total_ok for c in crawlers)
    total_err = sum(c.total_errors for c in crawlers)
    print(f"  TOTAL: ok={total_ok} erreurs={total_err}")


if __name__ == "__main__":
    main()
