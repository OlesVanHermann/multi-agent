#!/usr/bin/env python3
"""Extract page content via Chrome DevTools Protocol."""
import sys
import json
import urllib.request
import websocket

CHROME_PORT = 9222

def get_tab_ws_url(tab_id):
    """Get WebSocket URL for a tab."""
    url = f"http://127.0.0.1:{CHROME_PORT}/json"
    with urllib.request.urlopen(url, timeout=5) as response:
        tabs = json.loads(response.read().decode())
        for tab in tabs:
            if tab.get("id") == tab_id:
                return tab.get("webSocketDebuggerUrl")
    return None

def execute_js(ws_url, expression):
    """Execute JavaScript in page and return result."""
    ws = websocket.create_connection(ws_url, timeout=30)
    try:
        msg = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True}
        }
        ws.send(json.dumps(msg))
        result = json.loads(ws.recv())
        return result.get("result", {}).get("result", {}).get("value")
    finally:
        ws.close()

def extract_g2_data(tab_id):
    """Extract G2 review data from page."""
    ws_url = get_tab_ws_url(tab_id)
    if not ws_url:
        print(f"Tab {tab_id} not found", file=sys.stderr)
        return None
    
    js = """
    (function() {
        const data = {
            source: "G2",
            date_collecte: new Date().toISOString().split('T')[0],
            url: window.location.href
        };
        
        // Rating
        const ratingEl = document.querySelector('[itemprop="ratingValue"]') || 
                         document.querySelector('.fw-semibold.c-midnight-100');
        data.note_globale = ratingEl ? parseFloat(ratingEl.textContent.trim()) : null;
        
        // Review count
        const countEl = document.querySelector('[itemprop="reviewCount"]') ||
                        document.querySelector('span.c-midnight-80');
        if (countEl) {
            const match = countEl.textContent.match(/([\\d,]+)/);
            data.nombre_avis = match ? parseInt(match[1].replace(/,/g, '')) : null;
        }
        
        // Badge/category
        const badgeEl = document.querySelector('.badge') || document.querySelector('[data-badge]');
        data.badge = badgeEl ? badgeEl.textContent.trim() : null;
        
        const catEl = document.querySelector('a[href*="/categories/"]');
        data.categorie = catEl ? catEl.textContent.trim() : null;
        
        // Grid position
        const gridEl = document.querySelector('.grid-report-badge') || 
                       document.querySelector('[class*="leader"]');
        data.position_grid = gridEl ? gridEl.textContent.trim() : null;
        
        // Reviews
        data.avis_recents = [];
        const reviews = document.querySelectorAll('[itemprop="review"], .review-card, .paper--white');
        reviews.forEach((rev, i) => {
            if (i >= 10) return;
            const review = {};
            
            const dateEl = rev.querySelector('time, [itemprop="datePublished"]');
            review.date = dateEl ? dateEl.getAttribute('datetime') || dateEl.textContent.trim() : null;
            
            const rateEl = rev.querySelector('[class*="star"], [itemprop="ratingValue"]');
            review.note = rateEl ? parseFloat(rateEl.textContent || rateEl.dataset.rating) : null;
            
            const roleEl = rev.querySelector('.mt-4th, [itemprop="author"]');
            review.role = roleEl ? roleEl.textContent.trim() : null;
            
            const sizeEl = rev.querySelector('[class*="company-size"]');
            review.entreprise_taille = sizeEl ? sizeEl.textContent.trim() : null;
            
            const titleEl = rev.querySelector('h3, .review-title');
            review.titre = titleEl ? titleEl.textContent.trim() : null;
            
            const prosEl = rev.querySelector('[id*="pros"], .pros');
            review.pros = prosEl ? prosEl.textContent.trim().substring(0, 500) : null;
            
            const consEl = rev.querySelector('[id*="cons"], .cons');
            review.cons = consEl ? consEl.textContent.trim().substring(0, 500) : null;
            
            if (review.role || review.titre) data.avis_recents.push(review);
        });
        
        data.indicateurs_biais = {commentaire: "Avis B2B sollicités"};
        return JSON.stringify(data);
    })()
    """
    return execute_js(ws_url, js)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: cdp-extract.py <tab_id>", file=sys.stderr)
        sys.exit(1)
    result = extract_g2_data(sys.argv[1])
    if result:
        print(result)
    else:
        sys.exit(1)
