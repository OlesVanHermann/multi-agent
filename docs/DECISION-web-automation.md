# Décision : Périmètre du Web Automation

**EF-006** — Évaluation et isolation du web automation
**Agent :** 345 (Développeur)
**Date :** 2026-02-23
**Source :** Rapport 341, R3 — Spec 342 EF-006

---

## Contexte

Le module web automation (`scripts/chrome-bridge.py`, anciennement `chrome-shared.py`) représente **6 615 LOC (37.8%)** du code exécutable total (17 504 LOC). Le cœur du framework (bridge tmux-Redis-Claude) ne représente que **1 596 LOC (9.1%)**.

Cette disproportion soulève la question : le web automation est-il une fonctionnalité **core** ou un **outil annexe** ?

---

## Analyse

### Arguments pour "Core" (garder intégré)

1. **Utilisation intensive** — Les agents web automation sont parmi les plus actifs dans les projets déployés (crawling, scraping, monitoring).
2. **Intégration Redis** — chrome-bridge utilise le même Redis que le framework principal pour le mapping agent→tab.
3. **Convention d'agent** — Les agents Chrome suivent le même modèle de numérotation (3XX) et sont pilotés par le même bridge tmux.

### Arguments pour "Annexe" (extraire)

1. **Disproportion** — 37.8% du code pour une fonctionnalité que certains projets n'utilisent pas.
2. **Dépendance optionnelle** — Chrome + websocket-client ne sont pas nécessaires pour le fonctionnement de base du multi-agent.
3. **Complexité isolée** — Le protocole CDP est un domaine spécialisé, indépendant de l'orchestration d'agents.
4. **Déploiement** — Sur des serveurs headless (CI/CD, VM sans GUI), Chrome n'est pas disponible ni nécessaire.
5. **Maintenance** — Les mises à jour du protocole CDP n'impactent pas le cœur du framework.

### Évaluation des risques

| Critère | Intégré | Extrait |
|---------|---------|---------|
| Complexité déploiement | Tout est packagé | Deux packages à gérer |
| Taille du repo principal | 2 372 LOC de chrome | Allégé de 37.8% |
| Risque de régression | Plus élevé (plus de code) | Isolé |
| Tests indépendants | Mélangés | Séparés |

---

## Recommandation

**EXTRAIRE** le web automation dans un package séparé `multi-agent-crawl/`.

### Justification

1. Le framework multi-agent DOIT fonctionner sans Chrome (cas nominal : orchestration pure d'agents Claude).
2. Le refactoring EF-005 (décomposition en 4 modules) facilite l'extraction.
3. Le couplage avec le framework se limite au Redis (mapping agent→tab), facilement injectable.

### Structure proposée

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
├── tests/
│   └── test_chrome_bridge.py
└── requirements.txt          # websocket-client, redis, Pillow
```

### Interface avec le framework principal

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

*Document produit par Agent 345 — Réf CA-010*
