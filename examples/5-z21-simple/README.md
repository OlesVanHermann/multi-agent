# 5-z21-simple — Service API (Z21)

Exemple minimal d'un groupe Z21 : 6 agents spécialisés partageant 3 sous-contextes.

---

## Idée centrale

Le mode Z21 est conçu pour les projets larges où **une seule base de code** est découpée en zones (backend users, backend items, frontend). Chaque zone a son propre `archi.md` + `memory.md` + `methodology.md`. Les 6 agents partagent ces sous-contextes.

```
370-api/
├── 370-170  Master (routeur)
├── 370-370  Developer
├── 370-570  Tester
├── 370-770  Reviewer
├── 370-870  Coach
└── 370-970  Architect
```

---

## Structure

```
prompts/370-api/
├── 370-170-system.md       ← Master : route vers b-users, b-items, f-app
├── 370-170-memory.md       ← index des tâches par sous-contexte
├── 370-170-methodology.md  ← règles de dispatch
├── 370-370-system.md       ← Developer : charge archi.md + memory + methodology
├── 370-570-system.md       ← Tester : écrit et lance tests/test_{ctx}.py
├── 370-770-system.md       ← Reviewer : critères C1-C6
├── 370-870-system.md       ← Coach : met à jour memory.md + methodology.md
├── 370-970-system.md       ← Architect : crée/modifie sous-contextes
│
├── b-users/                ← Sous-contexte : gestion utilisateurs
│   ├── archi.md            ← endpoints, schéma SQL, fichiers concernés
│   ├── memory.md           ← état courant, historique des cycles
│   └── methodology.md      ← patterns d'implémentation validés
│
├── b-items/                ← Sous-contexte : CRUD items
│   ├── archi.md
│   ├── memory.md
│   └── methodology.md
│
└── f-app/                  ← Sous-contexte : frontend React
    ├── archi.md
    ├── memory.md
    └── methodology.md
```

---

## Workflow d'un cycle

```
1. Master (370-170) reçoit une tâche
         │
         ▼
2. Master identifie le sous-contexte (b-users, b-items, f-app)
         │
         ├──→ 370-370 Developer  "CONTEXT=b-items TASK=implémenter DELETE /items/{id}"
         │
3. Developer charge b-items/archi.md + memory.md + methodology.md
   → implémente, committe
         │
         ▼
4. 370-570 Tester  → écrit tests/test_b_items.py, lance pytest
         │
         ▼
5. 370-770 Reviewer → rapport C1-C6, VERDICT: APPROVE / REQUEST_CHANGES
         │
         ▼
6. 370-870 Coach  → met à jour b-items/memory.md + methodology.md
         │
         ▼
7. Master notifié → passe à la tâche suivante
```

---

## Différence avec MONO et X45

| | MONO | X45 | Z21 |
|--|------|-----|-----|
| Format prompt | 1 fichier `.md` | `system/memory/methodology` | 6 agents + sous-contextes |
| Feedback | Manuel | Boucle courte (Coach/Curator) | Boucle par sous-contexte (Coach) |
| Scaling | 1 agent = 1 tâche | 1 triangle = 1 worker | 6 agents = N sous-contextes |
| Cas d'usage | Tâches simples | Tâches itératives | Services multi-zones |

---

## Stack de l'exemple

- **Backend** : FastAPI + asyncpg (PostgreSQL)
- **Frontend** : React + Vite + Keycloak
- **Tests** : pytest-asyncio + httpx
- **Auth** : JWT via Keycloak

---

## Pour en savoir plus

[`docs/AGENT_Z21-METHODOLOGY.md`](../../docs/AGENT_Z21-METHODOLOGY.md)
