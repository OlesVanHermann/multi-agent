# Exemples - Projet MCP OnlyOffice

Ce dossier contient des exemples concrets tirés du projet **MCP OnlyOffice** qui a été développé avec ce système multi-agent.

---

## Projet MCP OnlyOffice

Serveur MCP pour manipulation de documents OnlyOffice (Excel, Word, PowerPoint, PDF) via CDP.

**Résultats obtenus avec ce système :**

| Métrique | Valeur |
|----------|--------|
| Outils MCP créés | 197+ |
| Formats supportés | 4 |
| Tests passés | 78/78 |
| Agents utilisés | 12 |

---

## Structure des exemples

```
examples/
├── README.md                    # Ce fichier
├── prompts/                     # Prompts spécialisés
│   ├── 300-dev-excel.md         # Agent dev Excel
│   ├── 301-dev-word.md          # Agent dev Word
│   ├── 302-dev-pptx.md          # Agent dev PowerPoint
│   └── 303-dev-pdf.md           # Agent dev PDF
├── knowledge/                   # Inventaires
│   ├── INVENTORY-EXCEL.md       # ~1350 fonctions API
│   ├── INVENTORY-WORD.md        # ~1400 fonctions API
│   ├── INVENTORY-PPTX.md        # ~650 fonctions API
│   └── INVENTORY-PDF.md         # ~269 fonctions API
├── specs/                       # Exemples de SPEC
│   └── SPEC-*.md
└── pool-requests/               # Exemples de PR
    ├── PR-DOC-example.md
    ├── PR-SPEC-example.md
    └── PR-TEST-example.md
```

---

## Comment ces exemples ont été créés

### 1. Agents Dev (300-303)

Créés par l'Agent 000 (Architect) à partir du template `3XX-developer.md.template` :

```
Template + Variables = Prompt spécialisé

Variables pour Excel :
  AGENT_ID = 300
  DOMAIN_NAME = Excel
  DOMAIN_LOWER = excel
  FUNCTION_PREFIX = excel
  REPO_NAME = mcp-onlyoffice-excel
  MAIN_FILE = server_multiformat.py
```

### 2. Inventaires

Créés en scannant la documentation API OnlyOffice :

```
api.onlyoffice.com/
├── spreadsheet-api/     → INVENTORY-EXCEL.md (63 classes)
├── text-document-api/   → INVENTORY-WORD.md (60 classes)
├── presentation-api/    → INVENTORY-PPTX.md (49 classes)
└── form-api/            → INVENTORY-PDF.md (12 classes)
```

### 3. Pool Requests

Cycle de vie d'une fonctionnalité :

```
PR-DOC (201) → PR-SPEC (200) → PR-SPEC assigned (3XX) → PR-TEST (3XX) → TEST (501)
     ↓              ↓                    ↓                    ↓            ↓
  pending        pending             assigned              pending      tests/
     ↓              ↓                    ↓                    ↓
   done           done                 done                 done
```

---

## Utilisation par Agent 000

Quand tu configures un nouveau projet :

1. **Lis ces exemples** pour comprendre le format
2. **Adapte** les prompts dev à ton domaine
3. **Crée** les inventaires selon ta source de données
4. **Utilise** les mêmes conventions de nommage

### Exemple : Adapter pour un projet Web

```
MCP OnlyOffice          →    Projet Web
─────────────────────────────────────────
300-dev-excel.md        →    300-dev-backend.md
301-dev-word.md         →    301-dev-frontend.md
302-dev-pptx.md         →    302-dev-api.md
INVENTORY-EXCEL.md      →    INVENTORY-BACKEND.md
excel_range_copy        →    backend_user_create
```

---

## Points clés à retenir

1. **Convention de nommage** : `PR-{TYPE}-{AGENT}-{Classe}_{Methode}.md`
2. **Flux unidirectionnel** : pending → assigned → done
3. **Git = persistance** : chaque action = commit
4. **Redis = notification** : communication temps réel entre agents
5. **Isolation Git** : chaque dev a son propre repo/branche

---

*Exemples du projet MCP OnlyOffice - Janvier 2026*
