#!/usr/bin/env python3
"""
==============================================================================
crawl.py -- Website Crawler via Chrome DevTools Protocol (CDP) on port 9222
==============================================================================

Full Architecture Overview
--------------------------
This script is a breadth-first web crawler that uses a headless Chrome browser
(accessed via the Chrome DevTools Protocol over WebSocket) to download and
render full HTML pages -- including JavaScript-rendered content -- from a
target domain. It is designed to run inside the multi-agent system, where
multiple agents may crawl concurrently, each isolated in their own Chrome tab.

File Storage System (On-Disk Database)
--------------------------------------
All crawl data lives under:
    ~/multi-agent/studies/<domain>/300/

The storage is split into three directories that together form a simple
on-disk key-value store:

    INDEX/   -- URL-to-SHA mapping files. Each file is named by the SHA-256
                hash of a URL, and its content is the original URL string.
                This acts as a reverse lookup: given a SHA filename in html/,
                you can find which URL it came from by reading INDEX/<sha>.
                Think of INDEX/ as the "registry" of all known URLs.

    html/    -- Downloaded HTML content. Each file is named <sha>.html.
                - Size 0 (empty): URL is registered but not yet downloaded
                  (acts as a download queue -- "placeholder" or "todo" marker).
                - Size > 0: URL has been successfully downloaded. The file
                  starts with a comment "<!-- URL: ... -->" followed by the
                  full HTML content.
                The presence of a 0-byte file is the mechanism by which new
                URLs are queued for download.

    FAILED/  -- Permanent failure markers. Each file is named by SHA and
                contains "url|reason|timestamp". Once a URL is marked failed
                (e.g., 404, 403, empty response), it is never retried. The
                corresponding empty html/ file is moved to ~/multi-agent/removed/
                (never deleted -- per project safety rules, rm is forbidden).

SHA-Based Deduplication System
------------------------------
Every URL is deduplicated via SHA-256 hashing:
    1. A URL string is normalized (strip fragments/params, http->https, etc.)
    2. The normalized URL is hashed: sha256(url.encode()).hexdigest()
    3. The resulting 64-char hex string becomes the filename in INDEX/ and html/
    4. Before registering a new URL, we check if html/<sha>.html already exists
       (downloaded) or FAILED/<sha> exists (permanently failed) -- if so, skip.
This ensures each unique URL is downloaded at most once, regardless of how
many pages link to it.

CDP Tab Isolation Per Agent
---------------------------
Multiple agents (e.g., agent 300, 301, 302) may run this crawler concurrently.
Each agent gets its own dedicated Chrome tab to avoid interference:
    - Agent ID is detected from: --agent-id flag > AGENT_ID env var > tmux session name
    - A Redis key "ma:chrome:tab:<agent_id>" stores the Chrome tab ID for that agent
    - On startup, the agent looks up its tab ID in Redis, verifies it still exists
      in Chrome, and gets the WebSocket debugger URL for that tab
    - If no tab exists (first run) or the old tab is stale (Chrome restarted),
      a new tab is created via CDP's /json/new endpoint and registered in Redis
    - If Redis is unavailable or agent ID is unknown, a new tab is created
      without isolation (works but risks conflicts with other agents)

Crawl Loop (Main Algorithm)
----------------------------
The crawl proceeds in two phases:

    Phase 1 -- Discovery Scan:
        Scan all already-downloaded HTML files (size > 100 bytes) in html/.
        Extract all <a href="..."> links from each file. For each new URL
        found that passes domain/pattern filters and isn't already known,
        register it (create INDEX/<sha> + touch empty html/<sha>.html).

    Phase 2 -- Download Loop (iterative):
        Repeat until no empty files remain:
        a) Find all 0-byte .html files in html/ (the download queue)
        b) For each, look up the URL from INDEX/<sha>
        c) Download the page via CDP (navigate + wait for load + get outerHTML)
        d) Check for HTTP error pages (404/403/500/502/503) by inspecting <title>
        e) If error: mark as FAILED, move empty file to removed/
        f) If success: write HTML content to the file, extract new URLs from it
           (which may create more 0-byte placeholders, feeding the next iteration)
        g) Stop when: no empty files remain, or no progress was made

URL Filtering System
--------------------
Two lists of regex patterns control which URLs are crawled:

    INCLUDE_PATTERNS: URL must match at least one pattern to be accepted.
        Default: [r'/en/', r'/fr/'] -- only crawl English and French pages.
        If the list is empty, all URLs pass the include check.

    EXCLUDE_PATTERNS: URL must NOT match any pattern. Used to skip:
        - URLs with query strings (?) or anchors (#)
        - Documentation paths (/docs/)
        - Binary files (.jpg, .png, .pdf, .zip, etc.)
        - Static assets (.css, .js, .json, .woff, etc.)

    These can be overridden via a config.json file in the study directory.

HTTP Error Detection
--------------------
Since CDP navigates to pages and retrieves the rendered HTML (not raw HTTP
status codes), error detection is heuristic -- based on the HTML <title> tag
and common error page phrases:
    - "404" in title, "page not found", "not found" in title -> 404
    - "403" in title, "forbidden" in title, "access denied" -> 403
    - "500" in title, "internal server error" -> 500
    - "502" in title, "bad gateway" -> 502
    - "503" in title, "service unavailable" -> 503
Pages detected as errors are marked as permanently FAILED and not retried.

Usage Examples
--------------
    python3 crawl.py example.com
    python3 crawl.py example.com --subdomains
    python3 crawl.py example.com --agent-id=300

Dependencies
------------
    - websockets (pip install websockets) -- for CDP WebSocket communication
    - aiohttp (pip install aiohttp) -- for CDP HTTP API (tab listing/creation)
    - redis (optional) -- for per-agent tab isolation; works without it
    - A running Chrome/Chromium instance with --remote-debugging-port=9222
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
# websockets is required for communicating with Chrome tabs over CDP WebSocket.
try:
    import websockets
except ImportError:
    sys.exit("pip install websockets")

# aiohttp is required for querying the CDP HTTP API (listing tabs, creating new tabs).
try:
    import aiohttp
except ImportError:
    sys.exit("pip install aiohttp")


# =============================================================================
# Global Configuration Constants
# =============================================================================

# CDP_PORT: The Chrome DevTools Protocol HTTP/WebSocket port.
# Chrome must be launched with --remote-debugging-port=<this port>.
# Can be overridden via CDP_PORT environment variable.
CDP_PORT = int(os.environ.get("CDP_PORT", 9222))  # Chrome partagé port 9222

# BASE_DIR: Root of the multi-agent system. All paths are relative to this.
BASE_DIR = Path.home() / "multi-agent"

# STUDIES_DIR: Parent directory for all crawl studies, organized by domain.
# Each domain gets its own subdirectory: studies/<domain>/300/
STUDIES_DIR = BASE_DIR / "studies"

# REMOVED_DIR: Safe deletion target. Files are moved here instead of being
# deleted (rm is forbidden by project safety rules -- see CLAUDE.md).
REMOVED_DIR = BASE_DIR / "removed"

# --- Per-study directory paths (initialized in main() once the domain is known) ---

# STUDY_DIR: The working directory for this crawl study.
#   Path: studies/<domain>/300/
#   The "300" subdirectory indicates this is a Developer-class agent's work area.
STUDY_DIR = None

# HTML_DIR: Where downloaded HTML files are stored, keyed by SHA-256 hash.
#   Path: studies/<domain>/300/html/
#   Files: <sha256>.html -- empty (0 bytes) = queued, non-empty = downloaded.
HTML_DIR = None

# INDEX_DIR: URL-to-SHA reverse lookup. Each file is named by SHA-256 hash
# of a URL, and its text content is the original URL.
#   Path: studies/<domain>/300/INDEX/
#   Files: <sha256> (no extension) -- content is the URL string.
INDEX_DIR = None

# FAILED_DIR: Permanent failure markers for URLs that returned errors.
#   Path: studies/<domain>/300/FAILED/
#   Files: <sha256> (no extension) -- content is "url|reason|timestamp".
FAILED_DIR = None

# CONFIG_FILE: Optional JSON config that can override include/exclude patterns.
#   Path: studies/<domain>/config.json
CONFIG_FILE = None

# ROOT_DOMAIN: The base domain (without www.) used for same-domain URL checks.
# For example, if crawling "www.example.com", ROOT_DOMAIN is "example.com".
# This allows matching both "example.com" and "www.example.com" as same-domain.
ROOT_DOMAIN = None  # Domaine racine pour matching sous-domaines

# INCLUDE_SUBDOMAINS: When True (--subdomains flag), URLs on any subdomain
# of ROOT_DOMAIN are accepted (e.g., docs.example.com, help.example.com).
# When False (default), only the exact domain and www. prefix are accepted.
INCLUDE_SUBDOMAINS = False  # --subdomains flag

# =============================================================================
# CDP Tab Isolation via Redis
# =============================================================================
# Each agent gets a dedicated Chrome tab to avoid navigation conflicts.
# The mapping agent_id -> Chrome tab_id is stored in Redis under this prefix.
# Full Redis key format: "ma:chrome:tab:<agent_id>" -> "<chrome_tab_id>"
REDIS_PREFIX = "ma:chrome:tab:"

# AGENT_ID: Identifies which multi-agent system agent is running this crawler.
# Set via --agent-id=XXX flag, AGENT_ID env var, or auto-detected from the
# tmux session name (e.g., "ma-agent-300" -> agent_id="300").
AGENT_ID = None  # --agent-id=XXX, AGENT_ID env, ou auto-detect tmux

# _redis_conn: Lazy-initialized Redis connection singleton.
# Set to False (not None) if connection failed, to avoid retrying.
_redis_conn = None


def _get_redis():
    """Get or create a lazy Redis connection. Returns None if unavailable.

    This uses a singleton pattern with three states:
        - None: not yet attempted (will try to connect)
        - <Redis instance>: connected successfully (reuse it)
        - False: connection failed (don't retry, return None)

    The Redis connection is used solely for CDP tab isolation (mapping
    agent IDs to Chrome tab IDs). The crawler works without Redis, but
    agents won't have isolated tabs and may interfere with each other.

    Returns:
        redis.Redis instance if connected, or None if unavailable.
    """
    global _redis_conn
    if _redis_conn is None:
        try:
            import redis as _redis_module
            _redis_conn = _redis_module.Redis(host='localhost', port=6379, decode_responses=True)
            # Verify the connection is alive with a PING command.
            _redis_conn.ping()
        except Exception:
            # Mark as permanently failed so we don't retry on every call.
            _redis_conn = False
    # Return the connection if it's a real Redis object, None if it's False.
    return _redis_conn if _redis_conn else None


def _detect_agent_id():
    """Detect the agent ID for CDP tab isolation.

    Detection priority (first match wins):
        1. Already set in global AGENT_ID (e.g., from --agent-id= flag)
        2. AGENT_ID environment variable
        3. Auto-detect from tmux session name:
           - "ma-agent-300" -> "300"
           - "agent-300"    -> "300"

    The agent ID is used as part of the Redis key that maps this agent
    to its dedicated Chrome tab. Without an agent ID, the crawler still
    works but creates a new (unisolated) tab each time.

    Returns:
        str: The detected agent ID, or None if undetectable.
    """
    global AGENT_ID
    # If already set (from CLI flag or previous call), return immediately.
    if AGENT_ID:
        return AGENT_ID

    # Try the AGENT_ID environment variable.
    agent_id = os.environ.get("AGENT_ID")
    if agent_id:
        AGENT_ID = agent_id
        return agent_id

    # Try to auto-detect from the tmux session name.
    # In the multi-agent system, each agent runs in a tmux session named
    # "{prefix}-agent-{id}" (e.g., "ma-agent-300" for agent 300).
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2
        )
        name = result.stdout.strip()
        # Parse the session name to extract the numeric agent ID.
        if name.startswith("ma-agent-"):
            AGENT_ID = name.split("ma-agent-")[1]
        elif name.startswith("agent-"):
            AGENT_ID = name.replace("agent-", "")
    except Exception:
        # tmux not available or not in a tmux session -- that's fine.
        pass
    return AGENT_ID


# =============================================================================
# URL Filtering Patterns
# =============================================================================
# These regex patterns control which discovered URLs are accepted for crawling.
# They can be overridden per-study via config.json.

# INCLUDE_PATTERNS: A URL must match AT LEAST ONE of these patterns to be crawled.
# If this list is empty, all URLs pass the include check (no restriction).
# Default: only crawl pages with /en/ or /fr/ in their path.
INCLUDE_PATTERNS = [
    r'/en/',   # Pages anglaises
    r'/fr/',   # Pages francaises
]

# EXCLUDE_PATTERNS: A URL must NOT match ANY of these patterns.
# Even if a URL passes the include check, matching any exclude pattern rejects it.
# This filters out non-HTML resources, documentation, and URLs with query params.
EXCLUDE_PATTERNS = [
    r'\?',     # Exclure les URLs avec parametres
    r'#',      # Exclure les ancres
    r'/docs/', # Exclure la doc (trop volumineux)
    # Exclude binary/media files by extension (images, videos, archives, etc.)
    r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|wav|avi)(\?|$)',  # Exclure fichiers binaires
    # Exclude non-HTML static assets (stylesheets, scripts, fonts, data files)
    r'\.(css|js|mjs|json|xml|txt|map|woff|woff2|ttf|eot|otf|rss|atom)(\?|$)',  # Exclure assets non-HTML
]


# =============================================================================
# Domain Matching
# =============================================================================

def is_same_domain(url_netloc: str, root_domain: str) -> bool:
    """Check whether a URL's netloc (host:port) belongs to the target domain.

    This determines if a discovered URL should be considered "same site" and
    therefore eligible for crawling. The behavior depends on the
    INCLUDE_SUBDOMAINS flag:

    Without --subdomains (strict mode, default):
        Only accepts the exact root domain or "www.<root_domain>".
        Example for root_domain="example.com":
            "example.com"       -> True
            "www.example.com"   -> True
            "docs.example.com"  -> False (subdomain rejected)

    With --subdomains (permissive mode):
        Accepts root domain and ALL subdomains.
        Example for root_domain="example.com":
            "example.com"       -> True
            "www.example.com"   -> True
            "docs.example.com"  -> True
            "a.b.example.com"   -> True

    Args:
        url_netloc: The netloc (hostname) from a parsed URL.
        root_domain: The target root domain (without www. prefix).

    Returns:
        True if the URL belongs to the same domain/site, False otherwise.
    """
    if not INCLUDE_SUBDOMAINS:
        # Mode strict: même domaine exact ou www.domaine
        return url_netloc == root_domain or url_netloc == f"www.{root_domain}"
    # Mode subdomains: accepte domaine exact + tous les sous-domaines
    return (url_netloc == root_domain or
            url_netloc.endswith(f".{root_domain}"))


# =============================================================================
# Configuration Loading
# =============================================================================

def load_config():
    """Load crawl configuration from the study's config.json file.

    The config file can override the default INCLUDE_PATTERNS and
    EXCLUDE_PATTERNS, allowing per-domain customization of the URL filter.

    Expected config.json format:
        {
            "include_patterns": ["/en/", "/fr/"],
            "exclude_patterns": ["\\\\?", "#", ...],
            "base_url": "https://www.example.com",
            "domain": "example.com"
        }

    Returns:
        dict: Configuration dictionary. Falls back to defaults if no config file exists.
    """
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"include_patterns": INCLUDE_PATTERNS, "exclude_patterns": EXCLUDE_PATTERNS}


# =============================================================================
# SHA-Based Deduplication Helpers
# =============================================================================

def url_to_sha(url: str) -> str:
    """Convert a URL to its SHA-256 hash (used as the filename in INDEX/ and html/).

    This is the core of the deduplication system. Every URL is mapped to a
    unique 64-character hexadecimal string. Two identical URLs always produce
    the same hash, so downloading the same URL twice is prevented.

    Args:
        url: The URL string to hash.

    Returns:
        str: 64-character lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(url.encode()).hexdigest()


def normalize_url(url: str) -> str:
    """Normalize a URL to a canonical form for consistent deduplication.

    Normalization steps:
        1. Strip fragment (#...) and query string (?...) -- these often
           point to the same page content.
        2. Upgrade http:// to https:// -- most sites redirect anyway,
           and this avoids treating http and https as different URLs.
        3. For bare two-part domains (e.g., "example.com"), add www. prefix --
           most sites redirect bare domain to www, so this avoids duplicates.
           Subdomains like "docs.example.com" are NOT prefixed.
        4. Strip trailing slash from deep paths (but keep it for the root path,
           e.g., "https://www.example.com/").

    Args:
        url: The raw URL string to normalize.

    Returns:
        str: The normalized URL, or empty string if normalization fails.
    """
    try:
        # Step 1: Strip fragment and query string.
        url = url.split('#')[0].split('?')[0]

        # Step 2: http -> https (most sites issue a 301 redirect anyway).
        if url.startswith('http://'):
            url = 'https://' + url[7:]

        # Step 3: Bare domain -> www. prefix for 2-part domains.
        # "example.com/page" -> "www.example.com/page"
        # but "docs.example.com/page" stays unchanged (it's a subdomain, not bare).
        # Only add www. to bare 2-part domains, not subdomains
        if ROOT_DOMAIN:
            parsed = urlparse(url)
            netloc = parsed.netloc
            parts = netloc.split('.')
            # Only add www if the netloc is exactly the root domain
            # AND it has 2 or fewer parts (e.g., "example.com", not "sub.example.com").
            if netloc == ROOT_DOMAIN and len(parts) <= 2:
                url = url.replace(f"://{ROOT_DOMAIN}", f"://www.{ROOT_DOMAIN}", 1)

        # Step 4: Strip trailing slash from deep paths, but not from root URL.
        # "https://www.example.com/page/" -> "https://www.example.com/page"
        # "https://www.example.com/" stays as-is (url.count('/') == 3).
        if url.endswith('/') and url.count('/') > 3:
            url = url.rstrip('/')
        return url
    except (ValueError, Exception):
        return ""


# =============================================================================
# URL Filtering
# =============================================================================

def should_include_url(url: str, config: dict) -> bool:
    """Determine whether a discovered URL should be registered for crawling.

    Applies a two-stage filter:
        1. INCLUDE check: URL must match at least one include pattern.
           If include_patterns is empty, all URLs pass this check.
        2. EXCLUDE check: URL must not match any exclude pattern.
           If a URL matches any exclude pattern, it is rejected.

    Both checks use case-insensitive regex matching (re.IGNORECASE).

    Args:
        url: The normalized URL to evaluate.
        config: Configuration dict with optional "include_patterns" and
                "exclude_patterns" keys (lists of regex strings).

    Returns:
        True if the URL should be crawled, False if it should be skipped.
    """
    include = config.get("include_patterns", INCLUDE_PATTERNS)
    exclude = config.get("exclude_patterns", EXCLUDE_PATTERNS)

    # Stage 1: Must match at least one include pattern (if any are defined).
    # Doit matcher au moins un pattern include
    if include:
        if not any(re.search(p, url, re.IGNORECASE) for p in include):
            return False

    # Stage 2: Must not match any exclude pattern.
    # Ne doit matcher aucun pattern exclude
    if exclude:
        if any(re.search(p, url, re.IGNORECASE) for p in exclude):
            return False

    return True


# =============================================================================
# HTML Link Extraction
# =============================================================================

def extract_urls_from_html(html: str, base_url: str, config: dict) -> set:
    """Extract and filter all valid URLs from an HTML document.

    Scans the HTML for href="..." attributes and resolves them against
    the base URL. Each discovered URL goes through:
        1. Skip non-HTTP schemes (javascript:, mailto:, tel:, #, data:)
        2. Resolve relative URLs against the base URL's scheme + netloc
        3. Normalize the URL (strip params, upgrade to https, etc.)
        4. Domain check: must belong to ROOT_DOMAIN (or its subdomains)
        5. Pattern filter: must pass should_include_url()

    Args:
        html: The raw HTML content to scan for links.
        base_url: The URL of the page this HTML was downloaded from.
                  Used to resolve relative URLs (e.g., "/page" -> "https://host/page").
        config: Configuration dict with include/exclude patterns.

    Returns:
        set: A set of normalized, filtered URL strings found in the HTML.
    """
    urls = set()
    # Simple regex to find href attributes in HTML tags.
    # Matches both single and double quotes: href="url" or href='url'.
    href_pattern = r'href=["\']([^"\']+)["\']'

    # Parse the base URL once for efficient relative URL resolution.
    parsed_base = urlparse(base_url)

    for match in re.finditer(href_pattern, html, re.IGNORECASE):
        try:
            url = match.group(1).strip()

            # Skip non-HTTP schemes that aren't actual navigable pages.
            if url.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue

            # Resolve relative URLs to absolute URLs.
            # Resoudre les URLs relatives (garde le sous-domaine d'origine)
            if url.startswith('/'):
                # Absolute path (e.g., "/page") -- prepend the base scheme + host.
                url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
            elif not url.startswith(('http://', 'https://')):
                # Relative path (e.g., "page" or "../page") -- use urljoin
                # to properly resolve against the base URL.
                url = urljoin(base_url, url)

            # Normalize for dedup consistency.
            url = normalize_url(url)
            if not url:
                continue

            # Domain check: only follow links within the same site.
            # Verifier le domaine (root domain pour inclure les sous-domaines)
            url_domain = urlparse(url).netloc
            if not is_same_domain(url_domain, ROOT_DOMAIN):
                continue
        except (ValueError, Exception):
            # Malformed URL -- skip silently.
            continue

        # Apply include/exclude pattern filters.
        if should_include_url(url, config):
            urls.add(url)

    return urls


# =============================================================================
# CDP (Chrome DevTools Protocol) Communication
# =============================================================================

async def get_ws_url():
    """Get the WebSocket debugger URL for this agent's dedicated Chrome tab.

    CDP Tab Isolation Flow:
        1. Detect the agent ID (from flag, env, or tmux session name).
        2. Look up the agent's tab ID in Redis (key: "ma:chrome:tab:<agent_id>").
        3. Query Chrome's /json endpoint to list all open tabs.
        4. If the agent's tab still exists in Chrome, return its WebSocket URL.
        5. If the tab is stale (Chrome was restarted), clean up Redis and proceed.
        6. Create a new blank tab via /json/new, register it in Redis, and return
           its WebSocket URL.

    This ensures each agent navigates in its own tab, preventing one agent's
    navigation from interrupting another agent's page load.

    Utilise le mapping Redis (ma:chrome:tab:{agent_id}) pour isoler
    chaque agent dans son propre onglet Chrome.
    Cree un onglet dedie si aucun n'existe.

    Returns:
        str: The WebSocket debugger URL (e.g., "ws://127.0.0.1:9222/devtools/page/<id>"),
             or None if Chrome is not reachable.
    """
    agent_id = _detect_agent_id()
    r = _get_redis()
    tab_id = None

    # Step 1: Look up the agent's existing tab ID from Redis.
    # Chercher le tab existant de l'agent dans Redis
    if agent_id and r:
        tab_id = r.get(f"{REDIS_PREFIX}{agent_id}")

    try:
        async with aiohttp.ClientSession() as session:
            # Step 2: List all currently open Chrome tabs via the CDP HTTP API.
            # Lister les tabs Chrome
            async with session.get(
                f"http://127.0.0.1:{CDP_PORT}/json",
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                tabs = await resp.json()

            # Step 3: If we have a stored tab_id, verify it still exists in Chrome.
            # Si l'agent a un tab, trouver son WebSocket URL
            if tab_id:
                for tab in tabs:
                    if tab.get("id") == tab_id and tab.get("webSocketDebuggerUrl"):
                        # Tab is still alive -- reuse it.
                        return tab["webSocketDebuggerUrl"]
                # If we reach here, the tab_id from Redis is stale (Chrome was
                # restarted, or the tab was manually closed). Clean up Redis.
                # Tab obsolete (Chrome redemarré, etc.) - nettoyer
                print(f"⚠ Tab {tab_id[:12]}... obsolete, creation nouveau...", file=sys.stderr)
                if r and agent_id:
                    r.delete(f"{REDIS_PREFIX}{agent_id}")

            # Step 4: Create a new dedicated tab for this agent.
            # Opens about:blank so the tab is ready for navigation.
            # Creer un onglet dedie pour cet agent
            async with session.put(
                f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank"
            ) as resp2:
                new_tab = await resp2.json()
                new_tab_id = new_tab.get("id")
                ws_url = new_tab.get("webSocketDebuggerUrl")
                # Register the new tab in Redis for future lookups.
                if new_tab_id and agent_id and r:
                    r.set(f"{REDIS_PREFIX}{agent_id}", new_tab_id)
                    print(f"✓ Tab dedie cree pour agent {agent_id}", file=sys.stderr)
                elif not agent_id:
                    # No agent ID means no isolation -- tab will work but isn't tracked.
                    print(f"⚠ Agent non identifie - tab sans isolation", file=sys.stderr)
                return ws_url
    except Exception as e:
        # Chrome is not running or not reachable on the expected port.
        print(f"Chrome CDP error: {e}", file=sys.stderr)
    return None


async def download_page(url: str, timeout: int = 15) -> str:
    """Download a single page via Chrome DevTools Protocol (CDP).

    This function:
        1. Connects to the agent's dedicated Chrome tab via WebSocket.
        2. Enables the Page domain (required to receive page lifecycle events).
        3. Navigates to the target URL.
        4. Waits for the Page.loadEventFired event (or times out after `timeout` seconds).
        5. Waits an additional 2 seconds for JavaScript rendering to complete.
        6. Evaluates document.documentElement.outerHTML to get the full rendered HTML.

    The 2-second post-load delay is important for Single Page Applications (SPAs)
    and sites that render content via JavaScript after the initial load event.

    The WebSocket max_size is set to 50MB to handle very large pages.

    Args:
        url: The URL to download.
        timeout: Maximum seconds to wait for the page load event (default: 15).

    Returns:
        str: The full rendered HTML content, or empty string on any error.
    """
    ws_url = await get_ws_url()
    if not ws_url:
        return ""

    try:
        # Connect to the Chrome tab's WebSocket with a large max_size
        # to handle pages with lots of inline content.
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            # CDP messages require sequential integer IDs to match requests
            # with their responses.
            msg_id = 1

            # Step 1: Enable the Page domain so we receive lifecycle events
            # (like Page.loadEventFired). Without this, navigation events are silent.
            # Enable Page
            await ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            # Step 2: Navigate to the target URL.
            # Navigate
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": url}
            }))
            msg_id += 1

            # Step 3: Wait for the Page.loadEventFired event, which signals
            # that the page's load event has fired (all resources loaded).
            # We poll WebSocket messages with 1-second timeouts, up to the
            # overall timeout limit.
            # Wait for load event
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < timeout:
                try:
                    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                    if response.get("method") == "Page.loadEventFired":
                        break
                except asyncio.TimeoutError:
                    # No message received in 1 second -- keep waiting.
                    continue

            # Step 4: Extra wait for JavaScript rendering.
            # Many modern sites fetch data and render content after the load event.
            # 2 seconds is a reasonable compromise between completeness and speed.
            # Extra wait for JS rendering
            await asyncio.sleep(2)

            # Step 5: Extract the fully rendered HTML from the page.
            # We use Runtime.evaluate to execute JavaScript in the page context
            # and return document.documentElement.outerHTML (the complete DOM).
            # Get HTML
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML"}
            }))

            # Read WebSocket messages until we find the response matching our msg_id.
            # Other messages (events, responses to earlier commands) are ignored.
            while True:
                response = json.loads(await ws.recv())
                if response.get("id") == msg_id:
                    # Extract the string value from the nested CDP response structure:
                    # {"id": N, "result": {"result": {"type": "string", "value": "..."}}}
                    result = response.get("result", {}).get("result", {})
                    return result.get("value", "")
    except Exception as e:
        print(f"    Error: {e}")
        return ""

    return ""


# =============================================================================
# File System Operations (On-Disk Queue Management)
# =============================================================================

def touch_file(sha: str):
    """Create an empty placeholder file in html/ to mark a URL as "queued".

    The empty (0-byte) .html file serves as a download queue entry.
    The crawl loop finds all 0-byte files, looks up their URLs from INDEX/,
    and downloads them. Once downloaded, the file is replaced with actual content.

    Cree un fichier vide (placeholder)

    Args:
        sha: The SHA-256 hash of the URL (used as the filename).
    """
    html_file = HTML_DIR / f"{sha}.html"
    if not html_file.exists():
        html_file.touch()


def is_empty(sha: str) -> bool:
    """Check if a URL's HTML file exists but is empty (i.e., queued for download).

    A 0-byte file means the URL is registered and waiting to be downloaded.

    Verifie si le fichier est vide (taille 0)

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if the file exists and is exactly 0 bytes.
    """
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size == 0


def is_downloaded(sha: str) -> bool:
    """Check if a URL has already been successfully downloaded.

    A file larger than 100 bytes is considered downloaded. The 100-byte
    threshold filters out any accidentally small files or partial writes.
    (A valid HTML page with the "<!-- URL: ... -->" comment header is
    always well over 100 bytes.)

    Verifie si deja telecharge (fichier existe ET non vide)

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if the file exists and has meaningful content (>100 bytes).
    """
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size > 100


def is_failed(sha: str) -> bool:
    """Check if a URL is permanently marked as failed.

    Failed URLs are never retried. The FAILED/ directory acts as a
    blacklist for URLs that returned HTTP errors (404, 403, 500, etc.)
    or produced empty responses.

    Verifie si en erreur permanente

    Args:
        sha: The SHA-256 hash of the URL.

    Returns:
        True if a failure marker exists in FAILED/ for this SHA.
    """
    return (FAILED_DIR / sha).exists()


def mark_failed(sha: str, url: str, reason: str = "download_error"):
    """Mark a URL as permanently failed and clean up its empty placeholder.

    This does two things:
        1. Creates a failure marker in FAILED/<sha> with metadata:
           "url|reason|timestamp" (e.g., "https://example.com/page|404_not_found|20260101_120000")
        2. Moves the empty placeholder from html/<sha>.html to removed/
           (per project safety rules, files are NEVER deleted with rm --
           they are always moved to the removed/ directory).

    Marque comme echoue avec la raison

    Args:
        sha: The SHA-256 hash of the URL.
        url: The original URL string (stored in the failure marker for reference).
        reason: A short code describing why it failed
                (e.g., "404_not_found", "403_forbidden", "empty_response").
    """
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    # Format: URL|reason|timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (FAILED_DIR / sha).write_text(f"{url}|{reason}|{timestamp}")
    # Deplacer le fichier vide vers removed/ (jamais rm)
    # Safety: move the 0-byte placeholder to removed/ instead of deleting it.
    html_file = HTML_DIR / f"{sha}.html"
    if html_file.exists() and html_file.stat().st_size == 0:
        REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(html_file), str(REMOVED_DIR / f"{timestamp}_{sha}.html"))


def get_empty_files() -> list:
    """Find all URLs that are queued for download (0-byte html files).

    Scans html/ for files with size 0, looks up each SHA in INDEX/ to get
    the original URL, and returns them as (sha, url) pairs. Files that are
    already marked as FAILED are excluded to avoid retrying known errors.

    This is effectively "reading the download queue."

    Retourne la liste des fichiers vides (sha, url depuis INDEX), en excluant les FAILED

    Returns:
        list: A list of (sha, url) tuples for URLs awaiting download.
    """
    empty = []
    for html_file in HTML_DIR.glob("*.html"):
        if html_file.stat().st_size == 0:
            sha = html_file.stem
            # IMPORTANT: Skip URLs that are already marked as permanently failed.
            # Without this check, failed URLs would be retried every iteration.
            # IMPORTANT: Verifier que l'URL n'est pas deja en erreur
            if is_failed(sha):
                continue
            # Look up the original URL from the INDEX directory.
            index_file = INDEX_DIR / sha
            if index_file.exists():
                url = index_file.read_text().strip()
                empty.append((sha, url))
    return empty


def register_url(url: str):
    """Register a new URL for crawling: create INDEX entry + empty HTML placeholder.

    This is the main entry point for adding URLs to the crawl queue.
    It creates two files:
        1. INDEX/<sha> -- contains the URL string (for reverse lookup)
        2. html/<sha>.html -- empty 0-byte file (marks it as "to download")

    If the URL is already downloaded (non-empty html file) or permanently
    failed, it is skipped to avoid duplicate work.

    Enregistre une URL: touch le fichier HTML + creer INDEX

    Args:
        url: The normalized URL to register.

    Returns:
        True if the URL was newly registered, False if it already existed
        (either downloaded or failed).
    """
    sha = url_to_sha(url)
    # Skip if already downloaded or permanently failed.
    if is_downloaded(sha) or is_failed(sha):
        return False

    # Touch le fichier HTML (placeholder vide)
    # Create the 0-byte HTML placeholder (the "download queue" entry).
    touch_file(sha)

    # Creer l'INDEX
    # Create the INDEX entry (SHA -> URL reverse mapping).
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_file = INDEX_DIR / sha
    if not index_file.exists():
        index_file.write_text(url)

    return True


# =============================================================================
# Main Crawl Logic
# =============================================================================

async def crawl_batch(config: dict) -> tuple:
    """Download all queued (empty) files in one batch.

    This is the core download loop for a single iteration:
        1. Get all 0-byte HTML files (the download queue).
        2. For each queued URL:
           a. Download the page via CDP.
           b. Check if the response is an HTTP error page (404, 403, 500, etc.)
              by inspecting the HTML content heuristically.
           c. If error: mark as FAILED, move placeholder to removed/.
           d. If success: save HTML (with URL comment header), then extract
              all links from the downloaded HTML and register new URLs
              (creating more 0-byte placeholders for the next iteration).
        3. Return counts of successes, failures, and newly discovered URLs.

    Telecharge les fichiers vides. Retourne (ok, errors, new_urls)

    Args:
        config: Configuration dict with include/exclude patterns.

    Returns:
        tuple: (ok_count, error_count, new_urls_found_count)
            - ok_count: Number of pages successfully downloaded.
            - error_count: Number of pages that failed (HTTP errors or empty).
            - new_urls_found_count: Number of NEW URLs discovered from downloaded pages.
    """
    empty_files = get_empty_files()
    if not empty_files:
        return 0, 0, 0

    ok = 0
    errors = 0
    new_urls_found = 0

    print(f"\n=== Batch: {len(empty_files)} fichiers vides a telecharger ===")

    for i, (sha, url) in enumerate(empty_files, 1):
        # Double-check: another iteration or concurrent process may have
        # already marked this URL as failed (race condition guard).
        # Double verification: URL deja en erreur?
        if is_failed(sha):
            print(f"[{i}/{len(empty_files)}] SKIP (deja en FAILED): {url[:50]}...")
            continue

        print(f"[{i}/{len(empty_files)}] {url[:70]}...")

        # Download the page via Chrome DevTools Protocol.
        html = await download_page(url)

        if html and len(html) > 500:
            # --- HTTP Error Detection ---
            # Since we use CDP (not raw HTTP), we don't get status codes.
            # Instead, we detect error pages by inspecting the HTML <title>
            # and common error phrases in the rendered content.
            # Detecter les pages d'erreur HTTP (404, 500, etc.)
            html_lower = html.lower()
            is_error_page = False
            error_reason = None

            # Check for 404 Not Found: title contains "404" or "page not found" or "not found"
            if '<title>404' in html_lower or 'page not found' in html_lower or 'not found</title>' in html_lower:
                is_error_page = True
                error_reason = "404_not_found"
            # Check for 403 Forbidden: title contains "403" or "forbidden" or "access denied"
            elif '<title>403' in html_lower or 'forbidden</title>' in html_lower or 'access denied' in html_lower:
                is_error_page = True
                error_reason = "403_forbidden"
            # Check for 500 Internal Server Error
            elif '<title>500' in html_lower or 'internal server error' in html_lower:
                is_error_page = True
                error_reason = "500_server_error"
            # Check for 502 Bad Gateway
            elif '<title>502' in html_lower or 'bad gateway' in html_lower:
                is_error_page = True
                error_reason = "502_bad_gateway"
            # Check for 503 Service Unavailable
            elif '<title>503' in html_lower or 'service unavailable' in html_lower:
                is_error_page = True
                error_reason = "503_unavailable"

            if is_error_page:
                # Page is an HTTP error -- mark as permanently failed.
                mark_failed(sha, url, error_reason)
                errors += 1
                print(f"    FAILED ({error_reason})")
            else:
                # --- Successful Download ---
                # Save the HTML content, prepending a comment with the source URL.
                # This comment is used later during link extraction (Phase 1) to
                # recover the base URL for resolving relative links.
                # Sauvegarder HTML (remplace le fichier vide)
                html_file = HTML_DIR / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                # Extract all links from the downloaded page and register
                # any new URLs as 0-byte placeholders for future download.
                # Extraire nouvelles URLs
                new_urls = extract_urls_from_html(html, url, config)
                for new_url in new_urls:
                    if register_url(new_url):
                        new_urls_found += 1

                ok += 1
                print(f"    OK ({len(html)//1024}KB, +{len(new_urls)} links)")
        else:
            # Response was empty or too small (<= 500 bytes) -- likely a
            # connection error, timeout, or Chrome rendering failure.
            mark_failed(sha, url, "empty_response")
            errors += 1
            print(f"    FAILED (empty_response)")

    return ok, errors, new_urls_found


# =============================================================================
# Entry Point
# =============================================================================

async def main():
    """Main entry point: parse arguments, set up directories, and run the crawl.

    The main function orchestrates the entire crawl in two phases:

    Phase 1 -- Discovery Scan:
        Scan all already-downloaded HTML files to discover new URLs that
        weren't previously known. This handles the case where HTML files
        were downloaded in a previous run but their links weren't fully
        extracted (e.g., the crawler was interrupted).

    Phase 2 -- Download Loop:
        Iteratively download all queued (0-byte) HTML files until:
        - No more empty files remain (all URLs are downloaded or failed), OR
        - No progress was made in the last iteration (stuck state).

    Each downloaded page may discover new URLs, which create new 0-byte
    placeholders, feeding subsequent iterations. This is a breadth-first
    crawl pattern.
    """
    global STUDY_DIR, HTML_DIR, INDEX_DIR, FAILED_DIR, CONFIG_FILE
    global ROOT_DOMAIN, INCLUDE_SUBDOMAINS, AGENT_ID

    # --- Argument Parsing ---
    # Separate positional arguments (domain) from flags (--subdomains, --agent-id).
    # Argument: domaine requis
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    # Show usage and list available studies if no domain is provided.
    if len(args) < 1:
        print("Usage: python3 crawl.py <domaine> [--subdomains] [--agent-id=XXX]")
        print("Exemple: python3 crawl.py example.com")
        print("         python3 crawl.py example.com --subdomains")
        print("         python3 crawl.py example.com --agent-id=300")
        print("\nOptions:")
        print("  --subdomains      Inclure les sous-domaines (docs.X, help.X, etc.)")
        print("  --agent-id=XXX    Forcer l'agent ID (sinon auto-detect tmux/env)")
        print("\nEtudes disponibles:")
        for d in STUDIES_DIR.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                print(f"  - {d.name}")
        return

    domain = args[0]
    INCLUDE_SUBDOMAINS = '--subdomains' in flags

    # Parse --agent-id=XXX from flags (overrides env var and tmux detection).
    for flag in flags:
        if flag.startswith('--agent-id='):
            AGENT_ID = flag.split('=', 1)[1]

    # ROOT_DOMAIN: strip "www." prefix so domain matching works for both
    # "example.com" and "www.example.com".
    # ROOT_DOMAIN = domaine sans www.
    ROOT_DOMAIN = domain.removeprefix("www.")

    # --- Initialize Directory Paths ---
    # All crawl data is stored under studies/<domain>/300/.
    # The "300" subdirectory corresponds to the Developer agent role in the
    # multi-agent system's numbering convention (300-399 = Developers).
    # Initialiser les chemins
    STUDY_DIR = STUDIES_DIR / domain / "300"
    HTML_DIR = STUDY_DIR / "html"        # Downloaded HTML files (sha.html)
    INDEX_DIR = STUDY_DIR / "INDEX"      # URL-to-SHA reverse lookup
    FAILED_DIR = STUDY_DIR / "FAILED"    # Permanent failure markers
    CONFIG_FILE = STUDIES_DIR / domain / "config.json"  # Optional per-domain config

    # The study directory must already exist (created by the study setup process).
    if not STUDY_DIR.exists():
        print(f"Erreur: Etude '{domain}' non trouvee dans {STUDIES_DIR}")
        return

    # --- Startup Information ---
    print(f"Domaine: {domain}")
    print(f"Repertoire: {STUDY_DIR}")
    if INCLUDE_SUBDOMAINS:
        print(f"Mode: sous-domaines actifs (*.{ROOT_DOMAIN})")

    # --- Agent Identification for CDP Tab Isolation ---
    # Identification agent pour isolation tab
    agent_id = _detect_agent_id()
    if agent_id:
        print(f"Agent: {agent_id} (tab isole via Redis)")
    else:
        print(f"⚠ Agent non identifie (utiliser --agent-id=XXX ou AGENT_ID env)")

    # --- Chrome Connectivity Check ---
    # Verify Chrome is running and accessible before starting the crawl.
    # Check Chrome
    ws_url = await get_ws_url()
    if not ws_url:
        print(f"Chrome not found on port {CDP_PORT}!")
        print()
        print("Lancer Chrome partage:")
        print("  $BASE/framework/chrome.sh start")
        print()
        return

    print(f"Chrome connected (tab dedie agent {agent_id or '?'})")

    # --- Directory Setup ---
    # Ensure html/ and INDEX/ directories exist (FAILED/ is created on demand).
    # Setup
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Load per-domain configuration (or use defaults).
    config = load_config()

    # =========================================================================
    # Phase 1: Discovery Scan
    # =========================================================================
    # Scan all previously downloaded HTML files (non-empty, >100 bytes) to
    # extract URLs that might not have been registered yet. This recovers
    # from interrupted crawls and ensures no links are missed.
    # Phase 1: Scanner les HTML existants (non vides) pour decouvrir de nouvelles URLs
    print(f"\nScan des HTML existants...")
    html_files = [f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 100]
    print(f"Fichiers HTML a scanner: {len(html_files)}")

    discovered = 0
    for html_file in html_files:
        try:
            content = html_file.read_text(errors='ignore')
            # Recover the base URL from the "<!-- URL: ... -->" comment that
            # was prepended when the file was saved. This is needed to correctly
            # resolve relative URLs found in the HTML.
            # Recuperer l'URL de base depuis le commentaire
            base_url = config.get("base_url", f"https://{config.get('domain', 'example.com')}")
            if content.startswith("<!-- URL:"):
                base_url = content.split("-->")[0].replace("<!-- URL:", "").strip()

            # Extract and register any new URLs found in this HTML file.
            new_urls = extract_urls_from_html(content, base_url, config)
            for url in new_urls:
                if register_url(url):
                    discovered += 1
        except Exception:
            # Skip files that can't be read (encoding issues, etc.).
            pass

    print(f"Nouvelles URLs decouvertes: {discovered}")

    # --- Pre-crawl Statistics ---
    # Stats
    total_files = len(list(HTML_DIR.glob("*.html")))
    empty_files = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
    print(f"\nTotal fichiers: {total_files}")
    print(f"Fichiers vides (a telecharger): {empty_files}")

    # =========================================================================
    # Phase 2: Download Loop (Iterative Breadth-First Crawl)
    # =========================================================================
    # Each iteration:
    #   1. Downloads all currently queued (0-byte) HTML files.
    #   2. For each successful download, extracts new URLs and registers them
    #      (creating new 0-byte placeholders).
    #   3. Checks if there are still empty files remaining.
    #   4. Stops when no empty files remain OR no progress was made.
    #
    # This loop naturally implements breadth-first crawling: all URLs at the
    # current "depth" are downloaded before moving to newly discovered URLs.
    # Phase 2: Boucle de crawl
    iteration = 0
    total_ok = 0
    total_errors = 0

    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print(f"{'='*60}")

        # Download all queued files and discover new URLs.
        ok, errors, new_urls = await crawl_batch(config)
        total_ok += ok
        total_errors += errors

        # Per-iteration summary.
        print(f"\nResultat iteration {iteration}:")
        print(f"  Telecharges: {ok}")
        print(f"  Erreurs: {errors}")
        print(f"  Nouvelles URLs decouvertes: {new_urls}")

        # Check how many 0-byte files remain (the queue size).
        # Verifier s'il reste des fichiers vides
        remaining = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
        print(f"  Fichiers vides restants: {remaining}")

        # Termination condition 1: queue is empty -- all URLs have been
        # either downloaded or marked as failed.
        if remaining == 0:
            print("\nPlus de fichiers vides, crawl termine!")
            break

        # Termination condition 2: no progress was made -- this can happen
        # if all remaining empty files are in a state where they can't be
        # downloaded (e.g., INDEX entry missing) but aren't marked FAILED.
        # This prevents infinite loops.
        if ok == 0 and errors == 0:
            print("\nAucun progres, arret.")
            break

    # =========================================================================
    # Final Summary
    # =========================================================================
    # Stats finales
    print(f"\n{'='*60}")
    print(f"CRAWL TERMINE")
    print(f"{'='*60}")
    print(f"Total telecharges: {total_ok}")
    print(f"Total erreurs: {total_errors}")
    # Count only files with actual content (>0 bytes) for the final valid count.
    final_count = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 0])
    print(f"Fichiers HTML valides: {final_count}")


if __name__ == "__main__":
    asyncio.run(main())
