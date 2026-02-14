#!/usr/bin/env python3
"""
Crawl complet via Chrome DevTools Protocol (CDP) port 9222

Source des URLs: INDEX/ (sha → url) + html/ vides (à télécharger)

Workflow:
1. Scan les HTML existants pour extraire de nouvelles URLs
2. Télécharge les fichiers html/ de taille 0 (lookup URL dans INDEX/)
3. Boucle jusqu'à ce qu'il n'y ait plus de fichiers vides

Filtrage:
- INCLUDE_PATTERNS: URLs qui DOIVENT matcher (ex: /fr/, /en/)
- EXCLUDE_PATTERNS: URLs exclues (?, #, /docs/, .jpg, .png, etc.)

Usage: python3 crawl.py <domaine>
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

try:
    import websockets
except ImportError:
    sys.exit("pip install websockets")

try:
    import aiohttp
except ImportError:
    sys.exit("pip install aiohttp")


CDP_PORT = int(os.environ.get("CDP_PORT", 9222))  # Chrome partagé port 9222
BASE_DIR = Path.home() / "multi-agent"
STUDIES_DIR = BASE_DIR / "studies"
REMOVED_DIR = BASE_DIR / "removed"

# Ces variables seront initialisées dans main() avec le domaine
STUDY_DIR = None
HTML_DIR = None
INDEX_DIR = None
FAILED_DIR = None
CONFIG_FILE = None
ROOT_DOMAIN = None  # Domaine racine pour matching sous-domaines
INCLUDE_SUBDOMAINS = False  # --subdomains flag

# --- Isolation Tab CDP par agent ---
REDIS_PREFIX = "ma:chrome:tab:"
AGENT_ID = None  # --agent-id=XXX, AGENT_ID env, ou auto-detect tmux

_redis_conn = None


def _get_redis():
    """Connexion Redis lazy (None si indisponible)."""
    global _redis_conn
    if _redis_conn is None:
        try:
            import redis as _redis_module
            _redis_conn = _redis_module.Redis(host='localhost', port=6379, decode_responses=True)
            _redis_conn.ping()
        except Exception:
            _redis_conn = False
    return _redis_conn if _redis_conn else None


def _detect_agent_id():
    """Detecte agent_id depuis --agent-id, AGENT_ID env, ou tmux session."""
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

# Patterns pour filtrer les URLs
INCLUDE_PATTERNS = [
    r'/en/',   # Pages anglaises
    r'/fr/',   # Pages francaises
]
EXCLUDE_PATTERNS = [
    r'\?',     # Exclure les URLs avec parametres
    r'#',      # Exclure les ancres
    r'/docs/', # Exclure la doc (trop volumineux)
    r'\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|tar|gz|mp4|mp3|wav|avi)(\?|$)',  # Exclure fichiers binaires
    r'\.(css|js|mjs|json|xml|txt|map|woff|woff2|ttf|eot|otf|rss|atom)(\?|$)',  # Exclure assets non-HTML
]


def is_same_domain(url_netloc: str, root_domain: str) -> bool:
    """Vérifie si un netloc appartient au même domaine (avec ou sans sous-domaines)"""
    if not INCLUDE_SUBDOMAINS:
        # Mode strict: même domaine exact ou www.domaine
        return url_netloc == root_domain or url_netloc == f"www.{root_domain}"
    # Mode subdomains: accepte domaine exact + tous les sous-domaines
    return (url_netloc == root_domain or
            url_netloc.endswith(f".{root_domain}"))


def load_config():
    """Charge la config depuis config.json"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"include_patterns": INCLUDE_PATTERNS, "exclude_patterns": EXCLUDE_PATTERNS}


def url_to_sha(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def normalize_url(url: str) -> str:
    try:
        url = url.split('#')[0].split('?')[0]
        # http → https (301 redirect)
        if url.startswith('http://'):
            url = 'https://' + url[7:]
        # bare domain → www (301 redirect): mistral.ai → www.mistral.ai
        # NEVER add www. to subdomains (workspace.google.com, developers.google.com, etc.)
        # Only add www. to bare 2-part domains (google.com → www.google.com)
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


def should_include_url(url: str, config: dict) -> bool:
    include = config.get("include_patterns", INCLUDE_PATTERNS)
    exclude = config.get("exclude_patterns", EXCLUDE_PATTERNS)

    # Doit matcher au moins un pattern include
    if include:
        if not any(re.search(p, url, re.IGNORECASE) for p in include):
            return False

    # Ne doit matcher aucun pattern exclude
    if exclude:
        if any(re.search(p, url, re.IGNORECASE) for p in exclude):
            return False

    return True


def extract_urls_from_html(html: str, base_url: str, config: dict) -> set:
    """Extrait les URLs d'un HTML"""
    urls = set()
    href_pattern = r'href=["\']([^"\']+)["\']'

    parsed_base = urlparse(base_url)

    for match in re.finditer(href_pattern, html, re.IGNORECASE):
        try:
            url = match.group(1).strip()

            if url.startswith(('javascript:', 'mailto:', 'tel:', '#', 'data:')):
                continue

            # Resoudre les URLs relatives (garde le sous-domaine d'origine)
            if url.startswith('/'):
                url = f"{parsed_base.scheme}://{parsed_base.netloc}{url}"
            elif not url.startswith(('http://', 'https://')):
                url = urljoin(base_url, url)

            url = normalize_url(url)
            if not url:
                continue

            # Verifier le domaine (root domain pour inclure les sous-domaines)
            url_domain = urlparse(url).netloc
            if not is_same_domain(url_domain, ROOT_DOMAIN):
                continue
        except (ValueError, Exception):
            continue

        if should_include_url(url, config):
            urls.add(url)

    return urls


async def get_ws_url():
    """Get WebSocket URL for this agent's dedicated Chrome tab.

    Utilise le mapping Redis (ma:chrome:tab:{agent_id}) pour isoler
    chaque agent dans son propre onglet Chrome.
    Cree un onglet dedie si aucun n'existe.
    """
    agent_id = _detect_agent_id()
    r = _get_redis()
    tab_id = None

    # Chercher le tab existant de l'agent dans Redis
    if agent_id and r:
        tab_id = r.get(f"{REDIS_PREFIX}{agent_id}")

    try:
        async with aiohttp.ClientSession() as session:
            # Lister les tabs Chrome
            async with session.get(
                f"http://127.0.0.1:{CDP_PORT}/json",
                timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                tabs = await resp.json()

            # Si l'agent a un tab, trouver son WebSocket URL
            if tab_id:
                for tab in tabs:
                    if tab.get("id") == tab_id and tab.get("webSocketDebuggerUrl"):
                        return tab["webSocketDebuggerUrl"]
                # Tab obsolete (Chrome redemarré, etc.) - nettoyer
                print(f"⚠ Tab {tab_id[:12]}... obsolete, creation nouveau...", file=sys.stderr)
                if r and agent_id:
                    r.delete(f"{REDIS_PREFIX}{agent_id}")

            # Creer un onglet dedie pour cet agent
            async with session.put(
                f"http://127.0.0.1:{CDP_PORT}/json/new?about:blank"
            ) as resp2:
                new_tab = await resp2.json()
                new_tab_id = new_tab.get("id")
                ws_url = new_tab.get("webSocketDebuggerUrl")
                if new_tab_id and agent_id and r:
                    r.set(f"{REDIS_PREFIX}{agent_id}", new_tab_id)
                    print(f"✓ Tab dedie cree pour agent {agent_id}", file=sys.stderr)
                elif not agent_id:
                    print(f"⚠ Agent non identifie - tab sans isolation", file=sys.stderr)
                return ws_url
    except Exception as e:
        print(f"Chrome CDP error: {e}", file=sys.stderr)
    return None


async def download_page(url: str, timeout: int = 15) -> str:
    """Download a single page via CDP"""
    ws_url = await get_ws_url()
    if not ws_url:
        return ""

    try:
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            msg_id = 1

            # Enable Page
            await ws.send(json.dumps({"id": msg_id, "method": "Page.enable"}))
            msg_id += 1

            # Navigate
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Page.navigate",
                "params": {"url": url}
            }))
            msg_id += 1

            # Wait for load event
            start = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start < timeout:
                try:
                    response = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                    if response.get("method") == "Page.loadEventFired":
                        break
                except asyncio.TimeoutError:
                    continue

            # Extra wait for JS rendering
            await asyncio.sleep(2)

            # Get HTML
            await ws.send(json.dumps({
                "id": msg_id,
                "method": "Runtime.evaluate",
                "params": {"expression": "document.documentElement.outerHTML"}
            }))

            while True:
                response = json.loads(await ws.recv())
                if response.get("id") == msg_id:
                    result = response.get("result", {}).get("result", {})
                    return result.get("value", "")
    except Exception as e:
        print(f"    Error: {e}")
        return ""

    return ""


def touch_file(sha: str):
    """Cree un fichier vide (placeholder)"""
    html_file = HTML_DIR / f"{sha}.html"
    if not html_file.exists():
        html_file.touch()


def is_empty(sha: str) -> bool:
    """Verifie si le fichier est vide (taille 0)"""
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size == 0


def is_downloaded(sha: str) -> bool:
    """Verifie si deja telecharge (fichier existe ET non vide)"""
    html_file = HTML_DIR / f"{sha}.html"
    return html_file.exists() and html_file.stat().st_size > 100


def is_failed(sha: str) -> bool:
    """Verifie si en erreur permanente"""
    return (FAILED_DIR / sha).exists()


def mark_failed(sha: str, url: str, reason: str = "download_error"):
    """Marque comme echoue avec la raison"""
    FAILED_DIR.mkdir(parents=True, exist_ok=True)
    # Format: URL|reason|timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (FAILED_DIR / sha).write_text(f"{url}|{reason}|{timestamp}")
    # Deplacer le fichier vide vers removed/ (jamais rm)
    html_file = HTML_DIR / f"{sha}.html"
    if html_file.exists() and html_file.stat().st_size == 0:
        REMOVED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(html_file), str(REMOVED_DIR / f"{timestamp}_{sha}.html"))


def get_empty_files() -> list:
    """Retourne la liste des fichiers vides (sha, url depuis INDEX), en excluant les FAILED"""
    empty = []
    for html_file in HTML_DIR.glob("*.html"):
        if html_file.stat().st_size == 0:
            sha = html_file.stem
            # IMPORTANT: Verifier que l'URL n'est pas deja en erreur
            if is_failed(sha):
                continue
            index_file = INDEX_DIR / sha
            if index_file.exists():
                url = index_file.read_text().strip()
                empty.append((sha, url))
    return empty


def register_url(url: str):
    """Enregistre une URL: touch le fichier HTML + creer INDEX"""
    sha = url_to_sha(url)
    if is_downloaded(sha) or is_failed(sha):
        return False

    # Touch le fichier HTML (placeholder vide)
    touch_file(sha)

    # Creer l'INDEX
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_file = INDEX_DIR / sha
    if not index_file.exists():
        index_file.write_text(url)

    return True


async def crawl_batch(config: dict) -> tuple:
    """Telecharge les fichiers vides. Retourne (ok, errors, new_urls)"""
    empty_files = get_empty_files()
    if not empty_files:
        return 0, 0, 0

    ok = 0
    errors = 0
    new_urls_found = 0

    print(f"\n=== Batch: {len(empty_files)} fichiers vides a telecharger ===")

    for i, (sha, url) in enumerate(empty_files, 1):
        # Double verification: URL deja en erreur?
        if is_failed(sha):
            print(f"[{i}/{len(empty_files)}] SKIP (deja en FAILED): {url[:50]}...")
            continue

        print(f"[{i}/{len(empty_files)}] {url[:70]}...")

        html = await download_page(url)

        if html and len(html) > 500:
            # Detecter les pages d'erreur HTTP (404, 500, etc.)
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

            if is_error_page:
                mark_failed(sha, url, error_reason)
                errors += 1
                print(f"    FAILED ({error_reason})")
            else:
                # Sauvegarder HTML (remplace le fichier vide)
                html_file = HTML_DIR / f"{sha}.html"
                html_file.write_text(f"<!-- URL: {url} -->\n{html}")

                # Extraire nouvelles URLs
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


async def main():
    global STUDY_DIR, HTML_DIR, INDEX_DIR, FAILED_DIR, CONFIG_FILE
    global ROOT_DOMAIN, INCLUDE_SUBDOMAINS, AGENT_ID

    # Argument: domaine requis
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 1:
        print("Usage: python3 crawl.py <domaine> [--subdomains] [--agent-id=XXX]")
        print("Exemple: python3 crawl.py scaleway.com")
        print("         python3 crawl.py mistral.ai --subdomains")
        print("         python3 crawl.py scaleway.com --agent-id=300")
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

    # Parse --agent-id=XXX
    for flag in flags:
        if flag.startswith('--agent-id='):
            AGENT_ID = flag.split('=', 1)[1]

    # ROOT_DOMAIN = domaine sans www. (ex: mistral.ai)
    ROOT_DOMAIN = domain.removeprefix("www.")

    # Initialiser les chemins
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
    if INCLUDE_SUBDOMAINS:
        print(f"Mode: sous-domaines actifs (*.{ROOT_DOMAIN})")

    # Identification agent pour isolation tab
    agent_id = _detect_agent_id()
    if agent_id:
        print(f"Agent: {agent_id} (tab isole via Redis)")
    else:
        print(f"⚠ Agent non identifie (utiliser --agent-id=XXX ou AGENT_ID env)")

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

    # Setup
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    config = load_config()

    # Phase 1: Scanner les HTML existants (non vides) pour decouvrir de nouvelles URLs
    print(f"\nScan des HTML existants...")
    html_files = [f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 100]
    print(f"Fichiers HTML a scanner: {len(html_files)}")

    discovered = 0
    for html_file in html_files:
        try:
            content = html_file.read_text(errors='ignore')
            # Recuperer l'URL de base depuis le commentaire
            base_url = config.get("base_url", f"https://{config.get('domain', 'example.com')}")
            if content.startswith("<!-- URL:"):
                base_url = content.split("-->")[0].replace("<!-- URL:", "").strip()

            new_urls = extract_urls_from_html(content, base_url, config)
            for url in new_urls:
                if register_url(url):
                    discovered += 1
        except Exception:
            pass

    print(f"Nouvelles URLs decouvertes: {discovered}")

    # Stats
    total_files = len(list(HTML_DIR.glob("*.html")))
    empty_files = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
    print(f"\nTotal fichiers: {total_files}")
    print(f"Fichiers vides (a telecharger): {empty_files}")

    # Phase 2: Boucle de crawl
    iteration = 0
    total_ok = 0
    total_errors = 0

    while True:
        iteration += 1
        print(f"\n{'='*60}")
        print(f"ITERATION {iteration}")
        print(f"{'='*60}")

        ok, errors, new_urls = await crawl_batch(config)
        total_ok += ok
        total_errors += errors

        print(f"\nResultat iteration {iteration}:")
        print(f"  Telecharges: {ok}")
        print(f"  Erreurs: {errors}")
        print(f"  Nouvelles URLs decouvertes: {new_urls}")

        # Verifier s'il reste des fichiers vides
        remaining = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size == 0])
        print(f"  Fichiers vides restants: {remaining}")

        if remaining == 0:
            print("\nPlus de fichiers vides, crawl termine!")
            break

        if ok == 0 and errors == 0:
            print("\nAucun progres, arret.")
            break

    # Stats finales
    print(f"\n{'='*60}")
    print(f"CRAWL TERMINE")
    print(f"{'='*60}")
    print(f"Total telecharges: {total_ok}")
    print(f"Total erreurs: {total_errors}")
    final_count = len([f for f in HTML_DIR.glob("*.html") if f.stat().st_size > 0])
    print(f"Fichiers HTML valides: {final_count}")


if __name__ == "__main__":
    asyncio.run(main())
