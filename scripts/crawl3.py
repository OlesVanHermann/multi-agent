#!/usr/bin/env python3
"""
Crawl v3 - Same as crawl2 (no language filter) + rate limiting + 429 detection.

Supports multi-domain round-robin crawling to avoid rate limiting.

Differences from crawl2.py:
- Single domain: 1 second delay between each page download (avoids 429)
- Multi-domain: round-robin provides natural delay, extra sleep adjusted by count
- Detects 429 "Too Many Requests" as error page

Use crawl3.py when a site returns 429 with crawl2.py.

Usage:
    python3 crawl3.py <domain>                              # Single domain (1s delay)
    python3 crawl3.py <d1> <d2> ... <d100> [--agent-id=XXX] # Multi-domain (max 100)

Multi-domain mode splits domains into batches of max 4 (round-robin per batch).
All batches run in PARALLEL (threads). Each batch has its own RR loop + Chrome tabs.

    Sites  Batches  Distribution
    1-4    1        [n]
    5      2        [3, 2]
    8      2        [4, 4]
    13     4        [4, 3, 3, 3]
    100    25       [4, 4, ..., 4]

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
import threading
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

# Rate limiting: 1 second between pages for single-domain mode.
# Multi-domain mode uses round-robin natural delay instead.
DELAY_BETWEEN_PAGES = 1

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
# UTILITIES
# =============================================================================

def url_to_sha(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def detect_agent_id(forced_id=None):
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

    # Extra sleep after page load, decreases with more domains
    SLEEP_BY_COUNT = {1: 1.0, 2: 0.5, 3: 0.24, 4: 0.12, 5: 0.06, 6: 0.02}

    def __init__(self, domain, include_subdomains=False, agent_suffix="",
                 extra_sleep=0.5, inter_page_delay=0):
        self.domain = domain
        self.root_domain = domain.removeprefix("www.")
        self.include_subdomains = include_subdomains
        self.agent_suffix = agent_suffix
        self.extra_sleep = extra_sleep
        self.inter_page_delay = inter_page_delay  # Additional delay between pages (crawl3 single-domain)

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

        # Queue
        self.pending = []
        self.pending_shas = set()

        # Counters
        self.total_ok = 0
        self.total_errors = 0
        self.total_new_urls = 0
        self.pages_processed = 0
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
        self.study_dir.mkdir(parents=True, exist_ok=True)
        self.html_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.study_dir / "FAILED").mkdir(parents=True, exist_ok=True)
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

    def _parse_js_links(self, js_links_raw: str) -> set:
        """Parse links extracted via JS querySelectorAll('a[href]').
        Uses ONLY global EXCLUDE_PATTERNS, ignores config.json include_patterns
        (which may target a different locale like ionos.fr vs ionos.com)."""
        urls = set()
        try:
            links = json.loads(js_links_raw)
        except (json.JSONDecodeError, TypeError):
            return urls
        for link in links:
            link = self.normalize_url(link)
            if not link:
                continue
            try:
                url_domain = urlparse(link).netloc
            except Exception:
                continue
            if not self.is_same_domain(url_domain):
                continue
            if EXCLUDE_PATTERNS and any(re.search(p, link, re.IGNORECASE) for p in EXCLUDE_PATTERNS):
                continue
            urls.add(link)
        return urls

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
                base_url = f"https://{self.domain}/"
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

        # Skip binary/non-HTML URLs (pdf, zip, images etc.)
        if re.search(r'\.(pdf|zip|tar|gz|mp4|mp3|wav|avi|exe|dmg|iso|doc|docx|xls|xlsx|ppt|pptx)(\?|$)', url, re.IGNORECASE):
            self.mark_failed(sha, url, "skipped_binary")
            return True

        # Inter-page delay (crawl3 rate limiting for single-domain mode)
        if self.inter_page_delay > 0 and self.pages_processed > 0:
            time.sleep(self.inter_page_delay)

        html = ""
        bridge_error = False
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
            # Wait for JS frameworks to hydrate (SPA need 1-2s after readyState)
            time.sleep(max(self.extra_sleep, 2.0))
            js_links_raw = self.cdp.evaluate(
                'JSON.stringify(Array.from(document.querySelectorAll("a[href]")).map(a=>a.href))'
            ) or "[]"
            html = self.cdp.get_html() or ""
        except Exception as e:
            print(f"  [{self.domain}] Error: {e}")
            html = ""
            js_links_raw = "[]"
            bridge_error = True

        self.pages_processed += 1

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
                ("429_rate_limited", ['429', 'too many requests']),
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
                print(f"  [{self.domain}] FAILED ({error_reason}): {url}")
            else:
                html_file = self.html_dir / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                new_urls = self.extract_urls_from_html(html, url)
                js_urls = self._parse_js_links(js_links_raw)
                all_urls = new_urls | js_urls
                new_count = 0
                for new_url in all_urls:
                    if self.register_and_queue(new_url):
                        new_count += 1
                        self.total_new_urls += 1

                self.total_ok += 1
                print(f"  [{self.domain}] OK ({len(html)//1024}KB, +{len(all_urls)} links): {url}")
        elif bridge_error:
            print(f"  [{self.domain}] SKIP (bridge error, will retry): {url}")
        else:
            self.mark_failed(sha, url, "empty_response")
            self.total_errors += 1
            print(f"  [{self.domain}] FAILED (empty): {url}")

        return True


# =============================================================================
# BATCH DISTRIBUTION
# =============================================================================

MAX_PER_BATCH = 4  # Max domains per round-robin batch (Chrome tabs)
MAX_DOMAINS = 100  # Max total domains per process


def split_into_batches(domains, max_per_batch=MAX_PER_BATCH):
    """Split domains into balanced batches of max_per_batch.

    Uses ceil(n/max_per_batch) batches with even distribution:
        5 → [3, 2]    8 → [4, 4]    13 → [4, 3, 3, 3]    100 → [4]*25
    """
    n = len(domains)
    if n <= max_per_batch:
        return [domains]
    num_batches = (n + max_per_batch - 1) // max_per_batch
    batches = []
    idx = 0
    for i in range(num_batches):
        size = n // num_batches + (1 if i < n % num_batches else 0)
        batches.append(domains[idx:idx + size])
        idx += size
    return batches


# =============================================================================
# CRAWL ONE BATCH (round-robin across max 4 domains)
# =============================================================================

def crawl_batch(batch_domains, agent_id, include_subdomains, domain_offset, inter_page_delay, precreated_tabs=None):
    """Crawl a batch of domains in round-robin. Returns list of crawlers with stats."""
    extra_sleep = DomainCrawler.SLEEP_BY_COUNT.get(len(batch_domains), 0.0)
    crawlers = []
    for i, domain in enumerate(batch_domains):
        suffix = f"_{domain_offset + i}"
        c = DomainCrawler(domain, include_subdomains, suffix, extra_sleep, inter_page_delay)
        if not c.validate():
            continue
        # Use pre-created tab if available
        if precreated_tabs and domain in precreated_tabs:
            c.tab_id = precreated_tabs[domain]
            c.cdp = _bridge.CDP(c.tab_id)
            crawlers.append(c)
            print(f"  [{domain}] Ready (tab={str(c.tab_id)[:12]}...)")
        elif c.setup_tab(agent_id):
            crawlers.append(c)
            print(f"  [{domain}] Ready (tab={str(c.tab_id)[:12]}...)")
        else:
            print(f"  [{domain}] SKIP: failed to create Chrome tab")

    if not crawlers:
        return []

    # Discovery
    for c in crawlers:
        discovered = c.discover()
        c.refresh_pending()
        total = len(list(c.html_dir.glob("*.html")))
        print(f"  [{c.domain}] {total} fichiers, {len(c.pending)} a telecharger, +{discovered} nouvelles URLs")

    # Round-robin crawl
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

    # Close Chrome tabs (free resources for next batch)
    for c in crawlers:
        if c.tab_id:
            try:
                _bridge.close_tab_by_id(c.tab_id)
            except Exception:
                pass

    return crawlers


# =============================================================================
# MAIN
# =============================================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 1:
        print(f"Usage: python3 crawl3.py <domain> [<domain2> ... <domain{MAX_DOMAINS}>] [options]")
        print()
        print("Single domain:  python3 crawl3.py example.com  (1s delay between pages)")
        print("Multi-domain:   python3 crawl3.py d1.com d2.com d3.com ... d100.com")
        print(f"                (batches of {MAX_PER_BATCH} in round-robin, max {MAX_DOMAINS} domains)")
        print()
        print("Options:")
        print("  --subdomains      Include subdomains")
        print("  --agent-id=XXX    Force agent ID")
        print()
        print(f"Mode: crawl3 (no language filter, delay={DELAY_BETWEEN_PAGES}s single-domain)")
        print("Transport: chrome-bridge.py (Extension + Native Messaging Host)")
        return

    domains = args[:MAX_DOMAINS]
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

    # Single-domain: add inter-page delay (the crawl3 specialty)
    # Multi-domain: round-robin provides natural delay, no extra inter-page delay
    inter_page_delay = DELAY_BETWEEN_PAGES if len(domains) == 1 else 0

    batches = split_into_batches(domains)
    batch_sizes = [len(b) for b in batches]
    print(f"Initialisation ({len(domains)} domaine(s), {len(batches)} batch(es): {batch_sizes})")
    print(f"Agent: {agent_id or '?'}")

    # =========================================================================
    # PRE-CREATE ALL TABS SEQUENTIALLY (avoid bridge saturation)
    # =========================================================================
    print(f"\nCreation de {len(domains)} tabs Chrome (sequentiel)...")
    precreated_tabs = {}  # domain -> tab_id
    domain_offset = 0
    for batch_idx, batch in enumerate(batches):
        for i, domain in enumerate(batch):
            suffix = f"_{domain_offset + i}"
            agent_key = f"{agent_id}{suffix}" if agent_id else None
            tab_id = None
            if agent_key:
                tab_id = _bridge.get_agent_tab(agent_key)
                if tab_id and _bridge.validate_target(tab_id):
                    precreated_tabs[domain] = tab_id
                    print(f"  [{domain}] reuse tab {str(tab_id)[:12]}...")
                    continue
                elif tab_id:
                    _bridge.cleanup_stale_target(agent_key)
            tab_id = _bridge.create_tab("about:blank")
            if tab_id:
                precreated_tabs[domain] = tab_id
                if agent_key:
                    _bridge.set_agent_tab(agent_key, tab_id)
                print(f"  [{domain}] tab {str(tab_id)[:12]}... created")
            else:
                print(f"  [{domain}] SKIP: failed to create tab")
            time.sleep(0.1)
        domain_offset += len(batch)
    print(f"  => {len(precreated_tabs)}/{len(domains)} tabs OK")

    # =========================================================================
    # CRAWL ALL BATCHES IN PARALLEL
    # =========================================================================
    all_results = [None] * len(batches)  # thread-safe: each index written by one thread
    domain_offset = 0
    threads = []

    def run_batch(idx, batch, offset):
        print(f"\n{'='*60}")
        print(f"BATCH {idx + 1}/{len(batches)}: {', '.join(batch)} (RR x{len(batch)})")
        print(f"{'='*60}")
        all_results[idx] = crawl_batch(batch, agent_id, include_subdomains, offset, inter_page_delay, precreated_tabs)

    for batch_idx, batch in enumerate(batches):
        t = threading.Thread(target=run_batch, args=(batch_idx, batch, domain_offset))
        threads.append(t)
        domain_offset += len(batch)

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    all_crawlers = []
    for result in all_results:
        if result:
            all_crawlers.extend(result)

    # =========================================================================
    # SUMMARY
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"CRAWL TERMINE ({len(domains)} domaines, {len(batches)} batches)")
    print(f"{'='*60}")
    for c in all_crawlers:
        final = len([f for f in c.html_dir.glob("*.html") if f.stat().st_size > 0])
        print(f"  [{c.domain}] ok={c.total_ok} erreurs={c.total_errors} HTML valides={final}")
    total_ok = sum(c.total_ok for c in all_crawlers)
    total_err = sum(c.total_errors for c in all_crawlers)
    print(f"  TOTAL: ok={total_ok} erreurs={total_err}")


if __name__ == "__main__":
    main()
