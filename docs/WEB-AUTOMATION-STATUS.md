# Statut du Web Automation — Classification Core/Annexe

**EF-006** — Évaluation et isolation du web automation
**Agent :** 345 (Développeur)
**Date :** 2026-02-24 (Cycle 5 — renommé depuis DECISION-web-automation.md)
**Source :** Rapport 341, R3 — Spec 342 EF-006 (cycle 7)

---

## Contexte

Le module web automation (`scripts/chrome-bridge.py`, anciennement `chrome-shared.py`) représente **6 615 LOC (37.8%)** du code exécutable total (17 504 LOC). Le cœur du framework (bridge tmux-Redis-Claude) ne représente que **1 596 LOC (9.1%)**.

---

## Grille de classification core/annexe (R-C6-6)

Application de la grille de 5 critères (spec 342 C7) à chaque fichier du domaine web automation :

| Fichier | C1: Import agent/orch | C2: >=3 imports | C3: Pipeline 200→345 | C4: CLI standalone | C5: 0 import entrant | **Classification** |
|---------|:---------------------:|:---------------:|:--------------------:|:-----------------:|:-------------------:|:------------------:|
| `chrome-shared.py` (2372 LOC) | non | 1 (chrome-bridge) | non | non | non | **annexe** |
| `chrome-bridge.py` (1482 LOC) | non | 0 | non | oui (CLI) | oui | **annexe** |
| `crawl.py` (1208 LOC) | non | 0 | non | oui (CLI) | oui | **annexe** |
| `crawl3.py` (856 LOC) | non | 0 | non | oui (CLI) | oui | **annexe** |
| `form-fill.py` (697 LOC) | non | 0 | non | oui (CLI) | oui | **annexe** |

**Résultat : 5/5 fichiers classifiés ANNEXE** — Aucun fichier du domaine web automation n'est importé par `agent.py`, `orchestrator.py`, ni utilisé dans la pipeline d'orchestration.

### Analyse détaillée

- **C1 (import agent/orch)** : `agent.py` et `orchestrator.py` ne contiennent aucun `import chrome`, `import crawl`, ou référence au domaine web automation.
- **C2 (fréquence imports)** : seul `chrome-bridge.py` importe `chrome-shared.py`. Aucun autre module du framework n'importe ces fichiers.
- **C3 (pipeline)** : la pipeline 200→341→342→345 ne touche pas au web automation.
- **C4 (CLI standalone)** : `chrome-bridge.py`, `crawl.py`, `crawl3.py`, `form-fill.py` sont tous des scripts CLI exécutés directement.
- **C5 (aucun import entrant)** : `crawl.py`, `crawl3.py`, `form-fill.py` n'ont aucun import entrant.

---

## Recommandation

**EXTRAIRE** le web automation dans un package séparé `multi-agent-crawl/`.

### Justification

1. Le framework multi-agent DOIT fonctionner sans Chrome (cas nominal : orchestration pure d'agents Claude).
2. Le refactoring EF-005 (décomposition en 4 modules) facilite l'extraction.
3. Le couplage avec le framework se limite au Redis (mapping agent→tab), facilement injectable.
4. **Tous les 5 critères de la grille R-C6-6 confirment la classification annexe.**

### Plan d'extraction

#### Fichiers à déplacer

```
multi-agent-crawl/
├── setup.py
├── README.md
├── chrome_bridge/
│   ├── __init__.py
│   ├── cdp_connection.py    # (EF-005 module 1)
│   ├── cdp_commands.py      # (EF-005 module 3)
│   ├── tab_manager.py       # (EF-005 module 2)
│   ├── redis_integration.py # (EF-005 module 4)
│   └── cli.py               # Point d'entrée CLI (remplace main())
├── crawl/
│   ├── crawl.py             # 1208 LOC
│   └── crawl3.py            # 856 LOC
├── tools/
│   ├── form_fill.py         # 697 LOC
│   └── chrome_bridge.py     # 1482 LOC (orchestration CLI)
├── tests/
│   └── test_chrome_bridge.py
└── requirements.txt          # websocket-client, redis, Pillow
```

#### Interface avec le framework principal

```python
# Dans multi-agent/ — installation optionnelle
# pip install multi-agent-crawl
# L'agent utilise directement la CLI :
# python -m chrome_bridge tab https://example.com
```

### Critères de succès

- [ ] `multi-agent-crawl/` est fonctionnel de manière autonome
- [ ] Le framework principal fonctionne sans le package crawl
- [ ] L'intégration Redis est injectée (pas de dépendance circulaire)
- [ ] Tous les tests EF-003 passent dans le package extrait

---

*Document produit par Agent 345 — Réf CA-010, EF-006, R-C6-6*
