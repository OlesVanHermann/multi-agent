#!/usr/bin/env python3
"""
CDP Latence - Automatise le test de latence via dotcom-tools.com
Agent 341
"""

import asyncio
import json
import sys
import websockets
import urllib.request
import re
from datetime import datetime

CHROME_PORT = 9222
TARGET_URL = "https://www.ionos.com"

async def run_latence_test(tab_id, domain):
    """Exécute le test de latence sur dotcom-tools."""

    ws_url = f"ws://127.0.0.1:{CHROME_PORT}/devtools/page/{tab_id}"

    async with websockets.connect(ws_url) as ws:
        msg_id = 1

        async def send_cmd(method, params=None):
            nonlocal msg_id
            cmd = {"id": msg_id, "method": method}
            if params:
                cmd["params"] = params
            await ws.send(json.dumps(cmd))
            msg_id += 1

            # Attendre la réponse
            while True:
                response = await ws.recv()
                data = json.loads(response)
                if "id" in data and data["id"] == msg_id - 1:
                    return data
                # Ignorer les events

        async def evaluate(expression):
            result = await send_cmd("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True
            })
            return result.get("result", {}).get("result", {}).get("value")

        # 1. Naviguer vers dotcom-tools
        print("Navigation vers dotcom-tools.com...")
        await send_cmd("Page.navigate", {"url": "https://www.dotcom-tools.com/website-speed-test"})
        await asyncio.sleep(5)

        # 2. Entrer l'URL à tester
        print(f"Entrée de l'URL: {domain}")
        js_enter_url = f"""
        (function() {{
            const input = document.querySelector('input[type="text"], input[type="url"], input#url, input[name="url"]');
            if (input) {{
                input.value = '{domain}';
                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }}
            return false;
        }})()
        """
        result = await evaluate(js_enter_url)
        print(f"URL entrée: {result}")

        # 3. Cliquer sur le bouton de test
        print("Lancement du test...")
        js_start_test = """
        (function() {
            const btn = document.querySelector('button[type="submit"], .btn-primary, button.start-test');
            if (btn) {
                btn.click();
                return true;
            }
            // Chercher par texte
            const buttons = document.querySelectorAll('button');
            for (const b of buttons) {
                if (b.textContent.toLowerCase().includes('test') || b.textContent.toLowerCase().includes('start')) {
                    b.click();
                    return true;
                }
            }
            return false;
        })()
        """
        await evaluate(js_start_test)

        # 4. Attendre les résultats (max 90s)
        print("Attente des résultats (60-90s)...")
        for i in range(90):
            await asyncio.sleep(1)

            # Vérifier si les résultats sont prêts
            js_check_results = """
            (function() {
                // Chercher un tableau de résultats ou des métriques
                const tables = document.querySelectorAll('table');
                const results = document.querySelectorAll('.result, .location-result, [class*="result"]');
                if (tables.length > 0 || results.length > 0) {
                    return true;
                }
                // Vérifier si "loading" n'est plus affiché
                const loading = document.querySelector('.loading, .spinner, [class*="loading"]');
                if (loading && loading.offsetParent !== null) {
                    return false;
                }
                return document.body.innerText.includes('ms') || document.body.innerText.includes('Load Time');
            })()
            """
            ready = await evaluate(js_check_results)
            if ready:
                print(f"Résultats prêts après {i+1}s")
                break
            if i % 10 == 0:
                print(f"  Attente... {i}s")

        # 5. Extraire les résultats
        print("Extraction des résultats...")
        js_extract = """
        (function() {
            const results = [];

            // Méthode 1: Chercher les lignes de tableau
            const rows = document.querySelectorAll('table tr, .location-row, .result-row');
            for (const row of rows) {
                const cells = row.querySelectorAll('td, .cell, span');
                if (cells.length >= 2) {
                    const text = row.innerText;
                    // Extraire région et temps
                    const match = text.match(/([A-Za-z\\s,]+)\\s+(\\d+)\\s*ms/);
                    if (match) {
                        results.push({
                            location: match[1].trim(),
                            time_ms: parseInt(match[2])
                        });
                    }
                }
            }

            // Méthode 2: Chercher dans le texte complet
            if (results.length === 0) {
                const text = document.body.innerText;
                const regex = /([A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*(?:,\\s*[A-Z]{2})?)\\s*[:\\-]?\\s*(\\d+(?:\\.\\d+)?)\\s*(?:ms|milliseconds)/g;
                let m;
                while ((m = regex.exec(text)) !== null) {
                    results.push({
                        location: m[1].trim(),
                        time_ms: parseFloat(m[2])
                    });
                }
            }

            return {
                page_title: document.title,
                results: results,
                raw_text: document.body.innerText.substring(0, 5000)
            };
        })()
        """

        data = await evaluate(js_extract)
        return data

def get_tab_id(agent_id):
    """Récupère le tab_id depuis Redis ou les onglets."""
    try:
        url = f"http://127.0.0.1:{CHROME_PORT}/json"
        with urllib.request.urlopen(url, timeout=2) as response:
            tabs = json.loads(response.read().decode())
            for tab in tabs:
                if "dotcom-tools" in tab.get("url", "").lower() or "dotcom-tools" in tab.get("title", "").lower():
                    return tab["id"]
            # Sinon prendre le premier about:blank ou page
            for tab in tabs:
                if tab.get("type") == "page":
                    return tab["id"]
    except Exception as e:
        print(f"Erreur: {e}")
    return None

def main():
    domain = sys.argv[1] if len(sys.argv) > 1 else "ionos.com"
    tab_id = sys.argv[2] if len(sys.argv) > 2 else get_tab_id(341)

    if not tab_id:
        print("Aucun onglet disponible", file=sys.stderr)
        sys.exit(1)

    print(f"=== Agent 341 - Test Latence ===")
    print(f"Domaine: {domain}")
    print(f"Tab ID: {tab_id}")
    print()

    try:
        data = asyncio.run(run_latence_test(tab_id, domain))

        # Formater les résultats
        output = {
            "source": "dotcom-tools",
            "date_test": datetime.now().strftime("%Y-%m-%d"),
            "url_testee": f"https://{domain}/",
            "resultats": data.get("results", []) if data else [],
            "raw_data": data
        }

        print("\n=== RÉSULTATS ===")
        print(json.dumps(output, indent=2, ensure_ascii=False))

        # Sauvegarder
        output_path = f"/Users/claude/multi-agent/studies/{domain}/304/latence.json"
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n✓ Sauvegardé: {output_path}")

    except Exception as e:
        print(f"Erreur: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
