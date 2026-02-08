#!/usr/bin/env python3
"""
Crawl v2 - Web crawler without mandatory language filter.

=============================================================================
FULL ARCHITECTURE OVERVIEW
=============================================================================

This script is a recursive web crawler that uses the Chrome DevTools Protocol
(CDP) via WebSocket to download and index web pages for a given domain.

KEY DIFFERENCE FROM crawl.py:
    crawl.py has INCLUDE_PATTERNS = [r'/en/', r'/fr/'] which means it ONLY
    accepts URLs that contain a language prefix like /en/ or /fr/ in the path.
    This is great for multilingual sites but causes crawl.py to discover ZERO
    URLs on sites that don't use language prefixes in their URL structure.

    crawl2.py sets INCLUDE_PATTERNS = [] (empty list). When the include list
    is empty, the should_include_url() function skips the include check
    entirely and accepts ALL URLs from the same domain. This makes it the
    right choice for sites without /en/, /fr/ style language prefixes.

    Everything else (exclude patterns, domain checking, CDP tab isolation,
    file storage, dedup logic) is identical between crawl.py and crawl2.py.

CRAWL LOOP (how the crawler works):
    1. DISCOVERY PHASE: Scan all existing non-empty HTML files in html/ to
       extract href links. Each new URL found is "registered" - an empty
       placeholder .html file is created (to be downloaded later) and the
       URL is recorded in INDEX/.
    2. DOWNLOAD PHASE: Find all empty (0-byte) .html files in html/, look
       up their URLs from INDEX/, and download each page via CDP.
    3. LINK EXTRACTION: After downloading each page, extract new URLs from
       the HTML and register them (creating more empty placeholders).
    4. REPEAT: Loop back to step 2 until no empty files remain (all pages
       downloaded) or no progress is made (stuck on errors).

FILE STORAGE SYSTEM (on-disk database):
    studies/<domain>/300/
        html/           - Downloaded HTML pages, named by SHA-256 hash
                          Empty (0-byte) files = pending download
                          Files > 100 bytes = successfully downloaded
                          Each file starts with <!-- URL: ... --> comment
        INDEX/          - URL-to-hash mapping (reverse lookup)
                          Filename = SHA-256 hash of the URL
                          Content = the original URL string
                          This lets us look up the URL for any hash
        FAILED/         - Permanent failure records
                          Filename = SHA-256 hash of the URL
                          Content = "url|reason|timestamp"
                          Once a URL is in FAILED/, it's never retried
        config.json     - Optional per-domain config overriding patterns

SHA-BASED DEDUPLICATION:
    Every URL is converted to a SHA-256 hash: url_to_sha(url) -> hex string.
    This hash serves as the unique filename for both html/ and INDEX/.
    Two identical URLs will always produce the same hash, so:
    - We never download the same URL twice (the file already exists)
    - We can quickly check if a URL was already seen (just check if file exists)
    - Filenames are safe (no special characters from URLs)
    - The INDEX/ directory provides reverse lookup: hash -> original URL

CDP TAB ISOLATION (per-agent Chrome tab management):
    Multiple agents may crawl different domains simultaneously using the same
    shared Chrome instance. To prevent agents from interfering with each other
    (e.g., one agent navigating away from another's page), each agent gets
    its own dedicated Chrome tab:
    - Agent ID is detected from: --agent-id flag > AGENT_ID env > tmux session name
    - Redis key "ma:chrome:tab:{agent_id}" maps each agent to a Chrome tab ID
    - get_ws_url() looks up or creates a dedicated tab, returning its WebSocket URL
    - If Redis is unavailable, the crawler still works but without tab isolation

ERROR DETECTION:
    Since CDP downloads return the full rendered HTML (not HTTP status codes),
    we detect error pages by inspecting the HTML content itself:
    - <title>404, "page not found", "not found</title>" -> 404
    - <title>403, "forbidden</title>", "access denied" -> 403
    - <title>500, "internal server error" -> 500
    - <title>502, "bad gateway" -> 502
    - <title>503, "service unavailable" -> 503
    Error pages are moved to FAILED/ and never retried.

URL FILTERING:
    Two-stage filter applied to every discovered URL:
    1. INCLUDE check: If INCLUDE_PATTERNS is non-empty, URL must match at
       least one pattern. In crawl2.py this list is EMPTY, so all URLs pass.
    2. EXCLUDE check: URL must NOT match any EXCLUDE_PATTERNS (query strings,
       anchors, binary files, assets, API endpoints, etc.)
    Additionally, URLs must belong to the same domain (or subdomain if
    --subdomains flag is used).

Usage: python3 crawl2.py <domaine> [--subdomains] [--agent-id=XXX]

Dependencies: websockets, aiohttp (pip install websockets aiohttp)
Requires: Chrome running with --remote-debugging-port=9222
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

# --- Dependency checks ---
# websockets is used to communicate with Chrome via CDP WebSocket protocol.
# If not installed, exit immediately with a helpful message.
try:
    import websockets
except ImportError:
    sys.exit("pip install websockets")

# aiohttp is used to query the Chrome HTTP endpoint (/json) to list tabs
# and create new ones. We use aiohttp instead of requests because the
# entire crawler is async (asyncio-based).
try:
    import aiohttp
except ImportError:
    sys.exit("pip install aiohttp")


# =============================================================================
# GLOBAL CONFIGURATION
# =============================================================================

# CDP_PORT: The port Chrome listens on for DevTools Protocol connections.
# Default is 9222, which is Chrome's standard remote debugging port.
# Can be overridden via the CDP_PORT environment variable.
CDP_PORT = int(os.environ.get("CDP_PORT", 9222))

# BASE_DIR: Root of the multi-agent system (~/multi-agent).
BASE_DIR = Path.home() / "multi-agent"

# STUDIES_DIR: Where all crawl studies are stored, organized by domain.
# Structure: studies/<domain>/300/html/, studies/<domain>/300/INDEX/, etc.
# The "300" subdirectory corresponds to the Developer agent role (3XX range)
# in the multi-agent system hierarchy.
STUDIES_DIR = BASE_DIR / "studies"

# REMOVED_DIR: Safe deletion target. Per the multi-agent system rules,
# files are NEVER deleted with rm - they are moved here instead.
# Failed downloads (empty HTML placeholders) are moved here when marked failed.
REMOVED_DIR = BASE_DIR / "removed"

# --- Per-domain paths (initialized in main() once the domain is known) ---
STUDY_DIR = None   # studies/<domain>/300/         - root of this crawl study
HTML_DIR = None    # studies/<domain>/300/html/     - downloaded HTML pages
INDEX_DIR = None   # studies/<domain>/300/INDEX/    - SHA->URL reverse mapping
FAILED_DIR = None  # studies/<domain>/300/FAILED/   - permanent failure records
CONFIG_FILE = None # studies/<domain>/config.json   - optional config overrides

# ROOT_DOMAIN: The base domain without "www." prefix (e.g., "example.com").
# Used for domain matching when filtering discovered URLs.
ROOT_DOMAIN = None

# INCLUDE_SUBDOMAINS: When True (--subdomains flag), accept URLs from any
# subdomain (e.g., docs.example.com, help.example.com). When False (default),
# only accept the exact domain and its www. variant.
INCLUDE_SUBDOMAINS = False

# =============================================================================
# CDP TAB ISOLATION VIA REDIS
# =============================================================================
# Each agent in the multi-agent system gets its own dedicated Chrome tab to
# prevent navigation conflicts. The mapping agent_id -> chrome_tab_id is
# stored in Redis under the key pattern "ma:chrome:tab:{agent_id}".

# REDIS_PREFIX: Key prefix for the agent-to-tab mapping in Redis.
REDIS_PREFIX = "ma:chrome:tab:"

# AGENT_ID: The numeric identifier of this agent (e.g., "300", "320").
# Detected from: --agent-id=XXX flag, AGENT_ID env var, or tmux session name.
# Used to look up / create a dedicated Chrome tab in Redis.
AGENT_ID = None

# _redis_conn: Lazy-initialized Redis connection. Set to False if Redis is
# unavailable (so we don't retry on every call). Set to the connection object
# on success.
_redis_conn = None


def _get_redis():
    """Get or create a lazy Redis connection.

    Returns the Redis connection object if available, or None if Redis
    is not running or the redis-py library is not installed.

    The connection is cached globally: on the first call it attempts to
    connect and ping Redis. If that fails, _redis_conn is set to False
    (a falsy sentinel) so subsequent calls return None immediately
    without retrying.
    """
    global _redis_conn
    if _redis_conn is None:
        try:
            import redis as _redis_module
            _redis_conn = _redis_module.Redis(host='localhost', port=6379, decode_responses=True)
            # ping() verifies the connection is alive; raises on failure
            _redis_conn.ping()
        except Exception:
            # Redis unavailable - set to False so we don't retry
            _redis_conn = False
    # Return the connection if truthy, None if False (unavailable)
    return _redis_conn if _redis_conn else None


def _detect_agent_id():
    """Detect the current agent's ID for CDP tab isolation.

    Detection priority (first match wins):
    1. Already set in AGENT_ID global (e.g., from --agent-id= flag)
    2. AGENT_ID environment variable
    3. Tmux session name: if running inside a tmux session named
       "ma-agent-300" or "agent-300", extract "300" as the agent ID

    Returns:
        The agent ID string (e.g., "300") or None if undetectable.

    The agent ID is used to create/find a dedicated Chrome tab in Redis,
    ensuring this agent's CDP navigation doesn't interfere with other
    agents sharing the same Chrome instance.
    """
    global AGENT_ID
    # If already set (e.g., from a previous call or --agent-id flag), return it
    if AGENT_ID:
        return AGENT_ID

    # Check environment variable (set by the agent runner or user)
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        AGENT_ID = agent_id
        return agent_id

    # Try to detect from tmux session name (format: "ma-agent-XXX" or "agent-XXX")
    # This works when the crawler is launched from within an agent's tmux session
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],  # #S = session name
            capture_output=True, text=True, timeout=2
        )
        name = result.stdout.strip()
        # MA_PREFIX-based session name: "ma-agent-300"
        if name.startswith("ma-agent-"):
            AGENT_ID = name.split("ma-agent-")[1]
        # Legacy session name format: "agent-300"
        elif name.startswith("agent-"):
            AGENT_ID = name.replace("agent-", "")
    except Exception:
        # Not in tmux, or tmux not installed - agent ID stays None
        pass
    return AGENT_ID


# =============================================================================
# URL FILTERING PATTERNS
# =============================================================================

# MAJOR DIFFERENCE FROM crawl.py:
# crawl.py has: INCLUDE_PATTERNS = [r'/en/', r'/fr/']
# crawl2.py has: INCLUDE_PATTERNS = [] (empty)
#
# When INCLUDE_PATTERNS is empty, should_include_url() skips the include check
# entirely, accepting ALL URLs from the domain. This is the whole reason
# crawl2.py exists - for sites that don't use /en/, /fr/ language prefixes.
INCLUDE_PATTERNS = []  # Empty = accept all URLs from the domain (no language filter)

# EXCLUDE_PATTERNS: URLs matching ANY of these patterns are rejected.
# This list is identical to crawl.py. It filters out:
# - URLs with query parameters (?) or fragment anchors (#)
# - Documentation paths (/docs/) and API endpoints (/api/)
# - Cloudflare internal paths (/cdn-cgi/)
# - Binary/media files (images, videos, archives, PDFs)
# - Static assets (CSS, JS, fonts, XML, etc.)
EXCLUDE_PATTERNS = [
    r'\?',     # Exclude URLs with query parameters (e.g., ?page=2&sort=date)
    r'#',      # Exclude fragment anchors (e.g., #section-title)
    r'/docs/', # Exclude documentation pages (often too voluminous to crawl)
    r'/api/',  # Exclude API endpoints (not browsable HTML pages)
    r'/cdn-cgi/', # Exclude Cloudflare internal paths (challenge pages, etc.)
    r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|wav|avi)(\?|$)',  # Exclude binary/media files
    r'\.(css|js|mjs|json|xml|txt|map|woff|woff2|ttf|eot|otf|rss|atom)(\?|$)',  # Exclude non-HTML assets
]


# =============================================================================
# DOMAIN MATCHING
# =============================================================================

def is_same_domain(url_netloc: str, root_domain: str) -> bool:
    """Check if a URL's network location (netloc) belongs to the target domain.

    This function controls which discovered links are considered "on-site"
    and eligible for crawling. It has two modes:

    Strict mode (default, INCLUDE_SUBDOMAINS=False):
        Only accepts the exact root domain or its www. variant.
        Example: root_domain="example.com" accepts:
            - example.com
            - www.example.com
        But rejects: docs.example.com, help.example.com

    Subdomain mode (--subdomains flag, INCLUDE_SUBDOMAINS=True):
        Accepts the root domain and any subdomain ending with .root_domain.
        Example: root_domain="example.com" accepts:
            - example.com
            - www.example.com
            - docs.example.com
            - api.help.example.com (any depth)

    Args:
        url_netloc: The netloc part of the URL (e.g., "www.example.com")
        root_domain: The base domain without www (e.g., "example.com")

    Returns:
        True if the URL belongs to the target domain, False otherwise.
    """
    if not INCLUDE_SUBDOMAINS:
        # Strict mode: exact domain or www.domain only
        return url_netloc == root_domain or url_netloc == f"www.{root_domain}"
    # Subdomain mode: accept domain itself + anything ending with .domain
    return (url_netloc == root_domain or
            url_netloc.endswith(f".{root_domain}"))


# =============================================================================
# CONFIGURATION
# =============================================================================

def load_config():
    """Load per-domain configuration from config.json if it exists.

    The config file (studies/<domain>/config.json) can override the default
    include and exclude patterns. This allows fine-tuning the crawl behavior
    per domain without modifying this script.

    Expected config.json structure:
    {
        "include_patterns": ["regex1", "regex2"],
        "exclude_patterns": ["regex3", "regex4"]
    }

    Returns:
        A dict with 'include_patterns' and 'exclude_patterns' keys.
        Falls back to the script's global defaults if no config file exists.
    """
    if CONFIG_FILE and CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"include_patterns": INCLUDE_PATTERNS, "exclude_patterns": EXCLUDE_PATTERNS}


# =============================================================================
# SHA-BASED DEDUPLICATION SYSTEM
# =============================================================================
# Every URL is hashed with SHA-256 to produce a deterministic, unique,
# filesystem-safe filename. This hash is used as:
#   - The filename in html/ (e.g., html/abc123...def.html)
#   - The filename in INDEX/ (e.g., INDEX/abc123...def containing the URL)
#   - The filename in FAILED/ (e.g., FAILED/abc123...def containing error info)
#
# This means:
#   - The same URL always maps to the same file (no duplicates)
#   - We can check if a URL was already seen by checking if the file exists
#   - We don't need a database - the filesystem IS the database

def url_to_sha(url: str) -> str:
    """Convert a URL to its SHA-256 hex digest.

    This is the core of the deduplication system. The same URL always
    produces the same 64-character hex string, which serves as a unique
    filename across the html/, INDEX/, and FAILED/ directories.

    Args:
        url: The full URL string (e.g., "https://www.example.com/page")

    Returns:
        64-character lowercase hex string (SHA-256 digest).
    """
    return hashlib.sha256(url.encode()).hexdigest()


# =============================================================================
# URL NORMALIZATION
# =============================================================================

def normalize_url(url: str) -> str:
    """Normalize a URL to a canonical form for consistent deduplication.

    Normalization steps:
    1. Strip fragment (#section) and query string (?key=value) - we only
       care about the base page, not specific sections or parameters
    2. Upgrade http:// to https:// - most sites redirect anyway, and this
       prevents treating http and https versions as different pages
    3. Add www. prefix to bare two-part domains (e.g., example.com ->
       www.example.com) - most sites redirect bare domains to www, so
       normalizing prevents duplicate downloads
    4. Strip trailing slash on deep paths (but keep it on root URLs) -
       /page/ and /page are usually the same content

    Args:
        url: The raw URL to normalize.

    Returns:
        The normalized URL string, or empty string on any error.
    """
    try:
        # Step 1: Strip fragment and query string
        url = url.split('#')[0].split('?')[0]

        # Step 2: Upgrade http to https (avoids treating them as different pages)
        if url.startswith('http://'):
            url = 'https://' + url[7:]

        # Step 3: Add www. to bare two-part domains (e.g., example.com -> www.example.com)
        # Only for the root domain, not for subdomains like docs.example.com
        if ROOT_DOMAIN:
            parsed = urlparse(url)
            netloc = parsed.netloc
            parts = netloc.split('.')
            # Only add www. if the netloc exactly matches the root domain
            # AND it's a simple two-part domain (not already a subdomain)
            if netloc == ROOT_DOMAIN and len(parts) <= 2:
                url = url.replace(f"://{ROOT_DOMAIN}", f"://www.{ROOT_DOMAIN}", 1)

        # Step 4: Strip trailing slash on deep paths
        # Keep trailing slash on root-level URLs (https://example.com/)
        # but remove it from paths like https://example.com/page/
        # The heuristic: if there are more than 3 slashes (scheme:// + path/),
        # the trailing slash is on a deep path and can be stripped
        if url.endswith('/') and url.count('/') > 3:
            url = url.rstrip('/')

        return url
    except (ValueError, Exception):
        return ""


# =============================================================================
# URL FILTERING
# =============================================================================

def should_include_url(url: str, config: dict) -> bool:
    """Determine if a URL should be included in the crawl based on patterns.

    Two-stage filtering:

    Stage 1 - INCLUDE check (allowlist):
        If include_patterns is non-empty, the URL MUST match at least one
        pattern to be accepted. In crawl.py this requires /en/ or /fr/.
        ** In crawl2.py, include_patterns is EMPTY, so this check is SKIPPED
        entirely - all URLs pass through to the exclude check. **
        This is THE key behavioral difference between crawl.py and crawl2.py.

    Stage 2 - EXCLUDE check (blocklist):
        The URL must NOT match ANY exclude pattern. This filters out
        query strings, anchors, binary files, assets, API endpoints, etc.

    Args:
        url: The full URL to check.
        config: Dict with 'include_patterns' and 'exclude_patterns' lists.

    Returns:
        True if the URL should be crawled, False if it should be skipped.
    """
    include = config.get("include_patterns", INCLUDE_PATTERNS)
    exclude = config.get("exclude_patterns", EXCLUDE_PATTERNS)

    # DIFFERENCE FROM crawl.py: When include is empty (as in crawl2.py),
    # this entire block is skipped, and ALL URLs pass through.
    # In crawl.py, include = [r'/en/', r'/fr/'], so only language-prefixed
    # URLs survive this filter.
    if include:
        if not any(re.search(p, url, re.IGNORECASE) for p in include):
            return False

    # Exclude check: reject URL if it matches ANY exclude pattern
    if exclude:
        if any(re.search(p, url, re.IGNORECASE) for p in exclude):
            return False

    return True


# =============================================================================
# HTML LINK EXTRACTION
# =============================================================================

def extract_urls_from_html(html: str, base_url: str, config: dict) -> set:
    """Extract and filter all href links from an HTML page.

    Scans the HTML for href="..." and href='...' attributes, resolves
    relative URLs against the base URL, normalizes them, filters by
    domain and include/exclude patterns, and returns the valid set.

    Processing steps for each found href:
    1. Skip non-HTTP schemes (javascript:, mailto:, tel:, data:, bare #)
    2. Resolve relative URLs:
       - Absolute path (/page) -> prepend scheme://netloc from base_url
       - Relative path (page) -> resolve with urljoin against base_url
       - Full URL (https://...) -> use as-is
    3. Normalize the URL (strip fragments, upgrade http, add www, etc.)
    4. Check domain ownership (must be same domain or allowed subdomain)
    5. Apply include/exclude pattern filtering

    Args:
        html: The raw HTML content of the page.
        base_url: The URL of the page (used to resolve relative links).
        config: Filter configuration with include/exclude patterns.

    Returns:
        A set of normalized, filtered URLs found in the page.
    """
    urls = set()
    # Regex to match href="value" or href='value' in HTML attributes
    href_pattern = r'href=["\']([^"\']+)["\']'

    # Parse the base URL to extract scheme and netloc for resolving relative paths
    parsed_base = urlparse(base_url)

    for match in re.finditer(href_pattern, html, re.IGNORECASE):
        try:
            url = match.group(1).strip()

            # Skip non-HTTP URL schemes that aren't actual web pages
            if url.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue

            # Resolve relative URLs to absolute URLs
            if url.startswith('/'):
                # Absolute path: prepend the scheme and netloc from the current page
                # This preserves the subdomain of the source page (important for
                # multi-subdomain sites)
                url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
            elif not url.startswith(('http://', 'https://')):
                # Relative path: use urljoin to resolve against the full base URL
                url = urljoin(base_url, url)

            # Normalize to canonical form (strip fragments, upgrade http, etc.)
            url = normalize_url(url)
            if not url:
                continue

            # Domain check: only accept URLs belonging to our target domain
            # (or its subdomains if --subdomains was specified)
            url_domain = urlparse(url).netloc
            if not is_same_domain(url_domain, ROOT_DOMAIN):
                continue
        except (ValueError, Exception):
            # Malformed URL - skip it silently
            continue

        # Apply include/exclude pattern filtering
        if should_include_url(url, config):
            urls.add(url)

    return urls


# =============================================================================
# CDP TAB MANAGEMENT (Chrome DevTools Protocol)
# =============================================================================

async def get_ws_url():
    """Get the WebSocket URL for this agent's dedicated Chrome tab.

    This function implements per-agent tab isolation using Redis as a
    coordination layer. The flow:

    1. Detect the agent ID (from flag, env, or tmux session)
    2. Look up the agent's assigned tab ID in Redis (ma:chrome:tab:{id})
    3. If found, verify the tab still exists in Chrome (tabs can disappear
       if Chrome restarts). If valid, return its WebSocket URL.
    4. If not found or stale, create a NEW blank tab in Chrome via the
       /json/new HTTP endpoint, store the mapping in Redis, and return
       the new tab's WebSocket URL.

    Why tab isolation matters:
        Multiple agents may run crawl2.py simultaneously for different domains.
        Without isolation, they'd share the same Chrome tab, and one agent's
        Page.navigate would interrupt another's page load. With dedicated tabs,
        each agent navigates independently.

    Returns:
        The WebSocket debugger URL string (e.g., "ws://127.0.0.1:9222/devtools/page/ABC123")
        or None if Chrome is not running or unreachable.
    """
    agent_id = _detect_agent_id()
    r = _get_redis()
    tab_id = None

    # Step 1: Look up existing tab assignment in Redis
    if agent_id and r:
        tab_id = r.get(f"{REDIS_PREFIX}{agent_id}")

    try:
        async with aiohttp.ClientSession() as session:
            # Step 2: Query Chrome for the list of all open tabs
            # The /json endpoint returns an array of tab descriptors
            async with session.get(
                f"http://127.0.0.1:{CDP_PORT}/json",
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                tabs = await resp.json()

            # Step 3: If we have a stored tab ID, verify it still exists in Chrome
            if tab_id:
                for tab in tabs:
                    if tab.get("id") == tab_id and tab.get("webSocketDebuggerUrl"):
                        # Tab still alive - reuse it
                        return tab["webSocketDebuggerUrl"]
                # Tab ID was in Redis but not found in Chrome (Chrome restarted,
                # tab was manually closed, etc.) - clean up the stale mapping
                print(f"⚠ Tab {tab_id[:12]}... obsolete, creation nouveau...", file=sys.stderr)
                if r and agent_id:
                    r.delete(f"{REDIS_PREFIX}{agent_id}")

            # Step 4: Create a new dedicated tab for this agent
            # PUT /json/new?about:blank creates a blank tab and returns its descriptor
            async with session.put(
                f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank"
            ) as resp2:
                new_tab = await resp2.json()
                new_tab_id = new_tab.get("id")
                ws_url = new_tab.get("webSocketDebuggerUrl")
                # Store the agent->tab mapping in Redis for future calls
                if new_tab_id and agent_id and r:
                    r.set(f"{REDIS_PREFIX}{agent_id}", new_tab_id)
                    print(f"✓ Tab dedie cree pour agent {agent_id}", file=sys.stderr)
                elif not agent_id:
                    # No agent ID detected - tab works but isn't tracked in Redis,
                    # so another call might create yet another tab
                    print(f"⚠ Agent non identifie - tab sans isolation", file=sys.stderr)
                return ws_url
    except Exception as e:
        # Chrome not running, wrong port, or network error
        print(f"Chrome CDP error: {e}", file=sys.stderr)
    return None


# =============================================================================
# PAGE DOWNLOAD VIA CDP
# =============================================================================

async def download_page(url: str, timeout: int = 15) -> str:
    """Download a single web page using Chrome DevTools Protocol (CDP).

    Instead of using HTTP requests directly (which miss JavaScript-rendered
    content), this function controls a real Chrome browser tab via WebSocket:

    1. Connect to the agent's dedicated Chrome tab via WebSocket
    2. Enable the Page domain (required to receive page lifecycle events)
    3. Navigate the tab to the target URL (Page.navigate)
    4. Wait for the Page.loadEventFired event (DOM + resources loaded)
    5. Wait an extra 2 seconds for JavaScript to finish rendering
    6. Execute JavaScript to capture the fully-rendered HTML
       (document.documentElement.outerHTML)

    This approach captures the final HTML after all JavaScript has executed,
    which is essential for single-page apps (SPAs) and dynamically rendered sites.

    Args:
        url: The URL to download.
        timeout: Maximum seconds to wait for page load event (default 15s).

    Returns:
        The full outer HTML of the page as a string, or empty string on error.
    """
    # Get the WebSocket URL for our dedicated Chrome tab
    ws_url = await get_ws_url()
    if not ws_url:
        return ""

    try:
        # Connect to Chrome tab via WebSocket with a generous max message size
        # (50MB) to handle large pages
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            # CDP uses incrementing message IDs to match requests with responses
            msg_id = 1

            # Step 1: Enable the Page domain to receive page lifecycle events
            # (like Page.loadEventFired). Without this, we can't detect when
            # the page finishes loading.
            await ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            # Step 2: Navigate the Chrome tab to the target URL
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": url}
            }))
            msg_id += 1

            # Step 3: Wait for the Page.loadEventFired event, which indicates
            # the page and its resources have finished loading.
            # We poll the WebSocket with 1-second receive timeouts, checking
            # each message for the load event.
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < timeout:
                try:
                    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                    if response.get("method") == "Page.loadEventFired":
                        break
                except asyncio.TimeoutError:
                    # No message received in 1 second - keep waiting
                    continue

            # Step 4: Extra 2-second delay for JavaScript rendering.
            # Many sites load content dynamically after the initial load event.
            # This gives SPAs time to render their content.
            await asyncio.sleep(2)

            # Step 5: Capture the fully-rendered HTML by executing JavaScript
            # in the page context. Runtime.evaluate runs arbitrary JS and
            # returns the result.
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML"}
            }))

            # Step 6: Read WebSocket messages until we get the response matching
            # our message ID. Other events (network, console, etc.) may arrive
            # before our response, so we skip those.
            while True:
                response = json.loads(await ws.recv())
                if response.get("id") == msg_id:
                    # Extract the HTML string from the nested result structure:
                    # response.result.result.value contains the actual HTML
                    result = response.get("result", {}).get("result", {})
                    return result.get("value", "")
    except Exception as e:
        print(f"    Error: {e}")
        return ""

    return ""


# =============================================================================
# FILE STATE MANAGEMENT
# =============================================================================
# The crawler uses the filesystem as its state database. Each URL's state is
# determined by the presence and size of files in html/, INDEX/, and FAILED/:
#
# State transitions:
#   NEW URL discovered -> touch_file() creates 0-byte html/{sha}.html
#                      -> register_url() creates INDEX/{sha} with the URL
#   DOWNLOAD attempt   -> Success: html/{sha}.html filled with content (>100 bytes)
#                      -> Failure: FAILED/{sha} created, empty html file moved to removed/
#
# Possible states for a URL (identified by its SHA):
#   - Not seen:     No file in html/ or INDEX/
#   - Pending:      html/{sha}.html exists with 0 bytes, INDEX/{sha} has URL
#   - Downloaded:   html/{sha}.html exists with >100 bytes
#   - Failed:       FAILED/{sha} exists with error info

def touch_file(sha: str):
    """Create an empty placeholder HTML file for a URL that needs downloading.

    An empty (0-byte) file in html/ signals "this URL has been discovered
    and needs to be downloaded." The crawl loop (get_empty_files) scans
    for these 0-byte files to build the download queue.

    Does nothing if the file already exists (whether empty or downloaded).

    Args:
        sha: The SHA-256 hash of the URL (used as filename).
    """
    html_file = HTML_DIR / f"{sha}.html"
    if not html_file.exists():
        html_file.touch()


def is_empty(sha: str) -> bool:
    """Check if a URL is in the "pending download" state.

    A URL is pending when its HTML file exists but has zero bytes
    (created by touch_file, not yet downloaded).

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if the file exists and is empty (0 bytes).
    """
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size == 0


def is_downloaded(sha: str) -> bool:
    """Check if a URL has been successfully downloaded.

    A URL is considered downloaded if its HTML file exists and is larger
    than 100 bytes. The 100-byte threshold filters out files that might
    contain only a tiny error message or a malformed response.

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if the file exists and has meaningful content (>100 bytes).
    """
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size > 100


def is_failed(sha: str) -> bool:
    """Check if a URL has been permanently marked as failed.

    Once a URL is in FAILED/, it is never retried. This prevents the
    crawler from endlessly re-attempting 404 pages, forbidden pages, etc.

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if a failure record exists for this URL.
    """
    return (FAILED_DIR / sha).exists()


def mark_failed(sha: str, url: str, reason: str = "download_error"):
    """Mark a URL as permanently failed and clean up its placeholder.

    Creates a failure record in FAILED/ containing the URL, reason, and
    timestamp. Then moves the empty placeholder HTML file to the removed/
    directory (following the multi-agent system's "never delete" rule).

    Failure record format: "url|reason|timestamp"
    Example: "https://example.com/page|404_not_found|20260208_143022"

    Args:
        sha: The SHA-256 hash of the URL.
        url: The original URL string (stored in the failure record).
        reason: A short error code describing why it failed
                (e.g., "404_not_found", "empty_response").
    """
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Write failure record: URL, reason, and timestamp separated by pipes
    (FAILED_DIR / sha).write_text(f"{url}|{reason}|{timestamp}")
    # Move the empty placeholder HTML file to removed/ (never delete files)
    html_file = HTML_DIR / f"{sha}.html"
    if html_file.exists() and html_file.stat().st_size == 0:
        REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(html_file), str(REMOVED_DIR / f"{timestamp}_{sha}.html"))


# =============================================================================
# DOWNLOAD QUEUE MANAGEMENT
# =============================================================================

def get_empty_files() -> list:
    """Build the download queue by finding all pending (empty) HTML files.

    Scans the html/ directory for 0-byte files, looks up their URLs from
    the INDEX/ directory, and returns them as a list of (sha, url) tuples.

    Files that are already marked as FAILED are excluded from the queue
    to prevent re-attempting known-bad URLs.

    Returns:
        List of (sha, url) tuples for URLs that need downloading.
    """
    empty = []
    for html_file in HTML_DIR.glob("*.html"):
        if html_file.stat().st_size == 0:
            sha = html_file.stem  # Filename without .html extension = SHA hash
            # Skip URLs that were already tried and failed permanently
            if is_failed(sha):
                continue
            # Look up the original URL from the INDEX directory
            index_file = INDEX_DIR / sha
            if index_file.exists():
                url = index_file.read_text().strip()
                empty.append((sha, url))
    return empty


def register_url(url: str):
    """Register a newly discovered URL for future download.

    This is the main entry point for adding new URLs to the crawl queue.
    It creates two things:
    1. An empty placeholder in html/{sha}.html (signals "needs download")
    2. An entry in INDEX/{sha} containing the URL (for reverse lookup)

    If the URL was already downloaded or already failed, it's skipped
    (deduplication via SHA hash).

    Args:
        url: The normalized URL to register.

    Returns:
        True if the URL was newly registered (not seen before).
        False if the URL was already downloaded, failed, or registered.
    """
    sha = url_to_sha(url)

    # Skip if already successfully downloaded or permanently failed
    if is_downloaded(sha) or is_failed(sha):
        return False

    # Create empty placeholder HTML file (marks it as "pending download")
    touch_file(sha)

    # Create the INDEX entry mapping SHA -> URL (for reverse lookup)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_file = INDEX_DIR / sha
    if not index_file.exists():
        index_file.write_text(url)

    return True


# =============================================================================
# BATCH DOWNLOAD (core crawl iteration)
# =============================================================================

async def crawl_batch(config: dict) -> tuple:
    """Download all pending pages and extract new URLs from them.

    This is one iteration of the crawl loop. It:
    1. Gets all empty (pending) HTML files from the download queue
    2. Downloads each page via CDP
    3. Checks if the downloaded content is an error page (404, 403, 500, etc.)
    4. If valid: saves the HTML and extracts new URLs to register
    5. If error: marks as permanently failed
    6. If empty response: marks as failed (CDP couldn't get content)

    Error detection works by inspecting the HTML title and body text,
    since CDP doesn't give us HTTP status codes directly. The page is
    rendered in Chrome, so we see whatever the browser shows for errors.

    Args:
        config: Filter configuration dict with include/exclude patterns.

    Returns:
        Tuple of (ok_count, error_count, new_urls_found):
        - ok_count: Number of pages successfully downloaded this batch
        - error_count: Number of pages that failed (404, empty, etc.)
        - new_urls_found: Number of new URLs discovered from downloaded pages
    """
    empty_files = get_empty_files()
    if not empty_files:
        return 0, 0, 0

    ok = 0
    errors = 0
    new_urls_found = 0

    print(f"\n=== Batch: {len(empty_files)} fichiers vides a telecharger ===")

    for i, (sha, url) in enumerate(empty_files, 1):
        # Double-check: another iteration may have marked this as failed
        # between get_empty_files() and now (defensive check)
        if is_failed(sha):
            print(f"[{i}/{len(empty_files)}] SKIP (deja en FAILED): {url[:50]}...")
            continue

        print(f"[{i}/{len(empty_files)}] {url[:70]}...")

        # Download the page via Chrome DevTools Protocol
        html = await download_page(url)

        # Check if we got meaningful content (more than 500 bytes)
        # Very short responses are likely error pages or empty shells
        if html and len(html) > 500:
            html_lower = html.lower()
            is_error_page = False
            error_reason = None

            # --- HTTP ERROR DETECTION FROM HTML CONTENT ---
            # Since we're using CDP (not HTTP requests), we don't get status codes.
            # Instead, we detect error pages by looking for telltale strings in
            # the HTML title and body text. These patterns catch most web servers'
            # default error pages.

            # 404 Not Found: page doesn't exist
            if '<title>404' in html_lower or 'page not found' in html_lower or 'not found</title>' in html_lower:
                is_error_page = True
                error_reason = "404_not_found"
            # 403 Forbidden: access denied (auth required, IP blocked, etc.)
            elif '<title>403' in html_lower or 'forbidden</title>' in html_lower or 'access denied' in html_lower:
                is_error_page = True
                error_reason = "403_forbidden"
            # 500 Internal Server Error: server-side crash
            elif '<title>500' in html_lower or 'internal server error' in html_lower:
                is_error_page = True
                error_reason = "500_server_error"
            # 502 Bad Gateway: upstream server unreachable (reverse proxy error)
            elif '<title>502' in html_lower or 'bad gateway' in html_lower:
                is_error_page = True
                error_reason = "502_bad_gateway"
            # 503 Service Unavailable: server overloaded or in maintenance
            elif '<title>503' in html_lower or 'service unavailable' in html_lower:
                is_error_page = True
                error_reason = "503_unavailable"

            if is_error_page:
                # Mark as permanently failed - never retry this URL
                mark_failed(sha, url, error_reason)
                errors += 1
                print(f"    FAILED ({error_reason})")
            else:
                # SUCCESS: Save the downloaded HTML content
                # The file replaces the empty 0-byte placeholder
                # We prepend a comment with the original URL for traceability
                # (used later by extract_urls_from_html to determine the base URL)
                html_file = HTML_DIR / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                # Extract new URLs from this page's links and register them
                # for future download (creating new empty placeholders)
                new_urls = extract_urls_from_html(html, url, config)
                for new_url in new_urls:
                    if register_url(new_url):
                        new_urls_found += 1

                ok += 1
                print(f"    OK ({len(html)//1024}KB, +{len(new_urls)} links)")
        else:
            # Empty or too-short response: CDP couldn't retrieve content.
            # This can happen if Chrome timed out, the page is blank,
            # or the WebSocket connection had issues.
            mark_failed(sha, url, "empty_response")
            errors += 1
            print(f"    FAILED (empty_response)")

    return ok, errors, new_urls_found


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main():
    """Main entry point: parse args, set up directories, and run the crawl loop.

    The main function orchestrates the entire crawl process:

    PHASE 0 - SETUP:
        Parse command-line arguments (domain, --subdomains, --agent-id),
        initialize directory paths, verify the study directory exists,
        connect to Chrome via CDP, and create html/INDEX directories.

    PHASE 1 - DISCOVERY (scan existing pages):
        Before downloading anything new, scan all already-downloaded HTML
        files to extract links. This is important for resumability: if the
        crawler was stopped and restarted, it re-discovers URLs from pages
        that were downloaded in previous runs.

    PHASE 2 - CRAWL LOOP:
        Repeatedly call crawl_batch() which downloads all pending (empty)
        files and discovers new URLs from them. Each batch may discover new
        URLs, creating more empty files, which the next iteration downloads.
        The loop terminates when:
        - No empty files remain (all URLs downloaded or failed)
        - No progress was made (0 downloads and 0 errors in a batch)
    """
    # Declare globals that we'll modify in this function
    global STUDY_DIR, HTML_DIR, INDEX_DIR, FAILED_DIR, CONFIG_FILE
    global ROOT_DOMAIN, INCLUDE_SUBDOMAINS, AGENT_ID

    # --- Argument parsing ---
    # Separate positional arguments (domain) from flags (--subdomains, --agent-id=XXX)
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    # Show usage if no domain provided
    if len(args) < 1:
        print("Usage: python3 crawl2.py <domaine> [--subdomains] [--agent-id=XXX]")
        print("Exemple: python3 crawl2.py example.com")
        print("         python3 crawl2.py example.com --subdomains")
        print("         python3 crawl2.py example.com --agent-id=320")
        print("\nOptions:")
        print("  --subdomains      Inclure les sous-domaines (docs.X, help.X, etc.)")
        print("  --agent-id=XXX    Forcer l'agent ID (sinon auto-detect tmux/env)")
        print("\nDifference avec crawl.py:")
        print("  - Pas de filtre de langue par defaut (/en/, /fr/)")
        print("  - Accepte toutes les URLs du meme domaine")
        print("\nUtiliser quand crawl.py ne decouvre pas d'URLs")
        return

    domain = args[0]
    # Check for --subdomains flag to enable subdomain crawling
    INCLUDE_SUBDOMAINS = '--subdomains' in flags

    # Parse --agent-id=XXX flag to force a specific agent identity
    for flag in flags:
        if flag.startswith('--agent-id='):
            AGENT_ID = flag.split('=', 1)[1]

    # Strip www. to get the root domain (used for domain matching).
    # "www.example.com" and "example.com" should be treated as the same domain.
    ROOT_DOMAIN = domain.removeprefix("www.")

    # --- Initialize directory paths ---
    # All paths are under studies/<domain>/300/ where "300" is the Developer
    # agent slot in the multi-agent hierarchy (3XX = Developer range)
    STUDY_DIR = STUDIES_DIR / domain / "300"
    HTML_DIR = STUDY_DIR / "html"       # Downloaded pages (SHA-named .html files)
    INDEX_DIR = STUDY_DIR / "INDEX"     # SHA->URL reverse mapping
    FAILED_DIR = STUDY_DIR / "FAILED"   # Permanent failure records
    CONFIG_FILE = STUDIES_DIR / domain / "config.json"  # Optional per-domain config

    # Verify the study directory was created (typically by the agent setup process)
    if not STUDY_DIR.exists():
        print(f"Erreur: Etude '{domain}' non trouvee dans {STUDIES_DIR}")
        return

    # --- Display startup information ---
    print(f"Domaine: {domain}")
    print(f"Repertoire: {STUDY_DIR}")
    print(f"Mode: crawl2 (sans filtre langue)")  # Highlight the key difference
    if INCLUDE_SUBDOMAINS:
        print(f"Sous-domaines: actifs (*.{ROOT_DOMAIN})")

    # --- Agent identification for CDP tab isolation ---
    agent_id = _detect_agent_id()
    if agent_id:
        print(f"Agent: {agent_id} (tab isole via Redis)")
    else:
        print(f"⚠ Agent non identifie (utiliser --agent-id=XXX ou AGENT_ID env)")

    # --- Verify Chrome is running and reachable ---
    ws_url = await get_ws_url()
    if not ws_url:
        print(f"Chrome not found on port {CDP_PORT}!")
        print()
        print("Lancer Chrome partage:")
        print("  $BASE/framework/chrome.sh start")
        return

    print(f"Chrome connected (tab dedie agent {agent_id or '?'})")

    # --- Create directories if they don't exist ---
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Load per-domain config (or fall back to global defaults)
    config = load_config()

    # =========================================================================
    # PHASE 1: DISCOVERY - Scan existing HTML files for new URLs
    # =========================================================================
    # This phase is critical for resumability. If the crawler was previously
    # interrupted, we re-scan all downloaded pages to rediscover any URLs
    # that might not have been registered yet. This ensures we don't miss
    # pages that were linked from already-downloaded content.
    print(f"\nScan des HTML existants...")
    # Only scan files with actual content (>100 bytes), not empty placeholders
    html_files = [f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 100]
    print(f"Fichiers HTML a scanner: {len(html_files)}")

    discovered = 0
    for html_file in html_files:
        try:
            content = html_file.read_text(errors='ignore')
            # Determine the base URL for resolving relative links.
            # Default to the domain root, but prefer the URL stored in the
            # <!-- URL: ... --> comment at the top of the file (if present)
            base_url = f"https://{domain}/"
            if content.startswith("<!-- URL:"):
                # Extract the URL from the comment: "<!-- URL: https://... -->"
                base_url = content.split("-->")[0].replace("<!-- URL:", "").strip()

            # Extract all links and register any new ones as pending downloads
            new_urls = extract_urls_from_html(content, base_url, config)
            for url in new_urls:
                if register_url(url):
                    discovered += 1
        except Exception:
            # Silently skip files that can't be read (encoding issues, etc.)
            pass

    print(f"Nouvelles URLs decouvertes: {discovered}")

    # --- Display current state statistics ---
    total_files = len(list(HTML_DIR.glob("*.html")))
    empty_files = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
    print(f"\nTotal fichiers: {total_files}")
    print(f"Fichiers vides (a telecharger): {empty_files}")

    # =========================================================================
    # PHASE 2: CRAWL LOOP - Download pending pages until done
    # =========================================================================
    # Each iteration downloads all currently-pending pages (empty files),
    # which may discover new URLs (creating more empty files), which are
    # then downloaded in the next iteration, and so on.
    #
    # Termination conditions:
    # 1. No empty files remain -> all pages downloaded or failed
    # 2. No progress in a batch (ok==0 and errors==0) -> stuck, bail out
    iteration = 0
    total_ok = 0
    total_errors = 0

    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print(f"{'='*60}")

        # Download all pending pages and collect stats
        ok, errors, new_urls = await crawl_batch(config)
        total_ok += ok
        total_errors += errors

        # Display iteration results
        print(f"\nResultat iteration {iteration}:")
        print(f"  Telecharges: {ok}")
        print(f"  Erreurs: {errors}")
        print(f"  Nouvelles URLs decouvertes: {new_urls}")

        # Count remaining empty files (pending downloads)
        remaining = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
        print(f"  Fichiers vides restants: {remaining}")

        # Termination check 1: all pages processed
        if remaining == 0:
            print("\nPlus de fichiers vides, crawl termine!")
            break

        # Termination check 2: no progress (no successful downloads, no new errors)
        # This prevents infinite loops when all remaining files are somehow
        # stuck (e.g., not in INDEX but still empty)
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
    # Count only files with actual content (not empty placeholders)
    final_count = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 0])
    print(f"Fichiers HTML valides: {final_count}")


# Standard Python entry point guard
if __name__ == "__main__":
    asyncio.run(main())
