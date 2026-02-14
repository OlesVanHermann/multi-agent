INTERDICTION D'HALUCINER
OBLIGATION d'OBEIR AUX PROMPTS. NE JAMAIS SORTIR DU CADRE DEFINIS PAR LE PROMPT
APPRENTISSAGE: Quand je suis guidé par un humain et que je reçois des instructions AUTRES que "go <entreprise>", c'est du nouveau savoir. Je DOIS mettre à jour mon prompt avec ces nouvelles expériences pour être autonome la prochaine fois.

# Conventions de Numérotation des Agents

## Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────┐
│                    HIÉRARCHIE DES AGENTS                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  9XX ARCHITECTS ──────────────────────────────────────────────┐ │
│  │ Créent la structure, les prompts, la pipeline              │ │
│  │ SEULS à pouvoir modifier les prompts                       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│  0XX SUPER-MASTERS ─────────────────────────────────────────────│
│  │ Coordination multi-projets                                   │
│  └──────────────────────────────────────────────────────────────│
│                              │                                   │
│                              ▼                                   │
│  1XX MASTERS ───────────────────────────────────────────────────│
│  │ Coordination d'un projet, dispatch aux workers               │
│  └──────────────────────────────────────────────────────────────│
│                              │                                   │
│         ┌────────────────────┼────────────────────┐             │
│         ▼                    ▼                    ▼             │
│  2XX EXPLORERS      3XX DEVELOPERS       4XX INTEGRATORS        │
│  │ Analyse API      │ Code              │ Merge Git             │
│  │ Création SPEC    │ Implémentation    │ Synchronisation       │
│  └──────────────────┴───────────────────┴───────────────────────│
│                              │                                   │
│                              ▼                                   │
│  5XX TESTERS ───────────────────────────────────────────────────│
│  │ Tests unitaires, intégration, QA                             │
│  └──────────────────────────────────────────────────────────────│
│                              │                                   │
│                              ▼                                   │
│  6XX RELEASERS ─────────────────────────────────────────────────│
│  │ Release, déploiement, publication                            │
│  └──────────────────────────────────────────────────────────────│
│                              │                                   │
│                              ▼                                   │
│  7XX DOCUMENTERS ───────────────────────────────────────────────│
│  │ Documentation, changelog, guides                             │
│  └──────────────────────────────────────────────────────────────│
│                              │                                   │
│                              ▼                                   │
│  8XX MONITORS ──────────────────────────────────────────────────│
│  │ Monitoring, alertes, support                                 │
│  └──────────────────────────────────────────────────────────────│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Plages de numérotation

| Plage | Type | Description | Capacité | Modifie prompts |
|-------|------|-------------|----------|-----------------|
| **000-099** | Super-Masters | Coordination multi-projets | 100 | ❌ |
| **100-199** | Masters | Coordination projet | 100 | ❌ |
| **200-299** | Explorers | Exploration, analyse, SPEC | 100 | ❌ |
| **300-399** | Developers | Développement code | 100 | ❌ |
| **400-499** | Integrators | Merge, sync, intégration | 100 | ❌ |
| **500-599** | Testers | Tests, validation, QA | 100 | ❌ |
| **600-699** | Releasers | Release, deploy | 100 | ❌ |
| **700-799** | Documenters | Documentation | 100 | ❌ |
| **800-899** | Monitors | Monitoring, support | 100 | ❌ |
| **900-999** | **Architects** | **Structure, prompts** | 100 | **✅ OUI** |

**Total: 1000 agents possibles (000-999)**

---

## Règle fondamentale

```
┌────────────────────────────────────────────────────────────────┐
│                                                                 │
│   SEUL L'AGENT 000 (ARCHITECT) PEUT MODIFIER:          │
│                                                                 │
│   • Les prompts (prompts/*.md)                          │
│   • La structure des agents                                    │
│   • La configuration de la pipeline                            │
│   • Les conventions                                            │
│                                                                 │
│   TOUS LES AUTRES AGENTS (0XX-8XX) ONT L'INTERDICTION DE:      │
│                                                                 │
│   • Modifier leur propre prompt                                │
│   • Modifier les prompts des autres agents                     │
│   • Changer la structure de la pipeline                        │
│                                                                 │
│   → S'ils ont besoin d'un changement, ils demandent à 000      │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## Workflow d'un nouveau projet

```
1. ARCHITECT (9XX) analyse le projet
        │
        ▼
2. ARCHITECT décide des agents nécessaires
        │
        ▼
3. ARCHITECT crée/adapte les prompts
        │
        ▼
4. ARCHITECT déploie la pipeline
        │
        ▼
5. SUPER-MASTER (0XX) prend le relais
        │
        ▼
6. Pipeline s'exécute (1XX → 8XX)
        │
        ▼
7. Si ajustement nécessaire → retour à ARCHITECT (9XX)
```

---

## Exemples de numérotation

### Super-Masters (0XX)
```
000 - super-master-principal
001 - super-master-backup
002 - super-master-projet-critique
```

### Masters (1XX)
```
100 - master-mcp-onlyoffice
101 - master-api-backend
102 - master-frontend
103 - master-mobile
```

### Explorers (2XX)
```
200 - explorer (PR-DOC → PR-SPEC)
201 - doc-generator (API Doc → PR-DOC)
202 - analyzer-coverage
203 - analyzer-performance
```

### Developers (3XX)
```
300 - dev-excel
301 - dev-word
302 - dev-pptx
303 - dev-pdf
304 - dev-typescript
305 - dev-python
306 - dev-rust
307 - dev-go
...
350 - dev-frontend-react
351 - dev-frontend-vue
352 - dev-backend-node
353 - dev-backend-django
```

### Integrators (4XX)
```
400 - merge-principal
401 - merge-hotfix
402 - sync-repos
403 - sync-forks
```

### Testers (5XX)
```
500 - test-unit
501 - test-creator (création de tests)
502 - test-mapper (mapping tests ↔ PR-DOC)
503 - test-performance
504 - test-security
505 - qa-review
```

### Releasers (6XX)
```
600 - release-prod
601 - release-staging
602 - release-beta
603 - deploy-docker
604 - deploy-kubernetes
605 - publish-npm
```

### Documenters (7XX)
```
700 - doc-api
701 - doc-user
702 - doc-dev
703 - changelog-writer
704 - readme-updater
```

### Monitors (8XX)
```
800 - monitor-health
801 - monitor-performance
802 - monitor-errors
803 - alerter-slack
804 - alerter-email
805 - support-tier1
```

### Architects (9XX)
```
900 - architect-principal
901 - architect-backup
902 - architect-specialist-devops
903 - architect-specialist-ml
```

---

## Fichiers de prompts

```
prompts/
├── CONVENTIONS.md              # Ce fichier
├── 000-super-master.md
├── 100-master.md
├── 200-explorer.md
├── 300-dev-excel.md
├── 301-dev-word.md
├── 302-dev-pptx.md
├── 303-dev-pdf.md
├── 400-merge.md
├── 500-test.md
├── 600-release.md
├── 700-doc.md
├── 800-monitor.md
└── 900-architect.md            # SEUL à pouvoir modifier ce dossier
```

---

## Scaling

| Taille projet | Super-Masters | Masters | Workers | Architects |
|---------------|---------------|---------|---------|------------|
| Petit | 0 | 1 | 5 | 1 |
| Moyen | 1 | 3 | 20 | 1 |
| Grand | 2 | 10 | 50 | 2 |
| Très grand | 5 | 20 | 100+ | 3 |

---

## Mapping Agents → Profiles Claude

Les agents sont exécutés via différents abonnements Claude (profiles).

**Profiles disponibles :**
- `octave1`, `octave2` - forts/faibles
- `miro1`, `miro2` - forts/faibles
- `stef1`, `stef2` - forts/faibles
- `shadow1`, `shadow2` - forts/faibles

**Configuration actuelle** (définie dans `$BASE/scripts/start-agents.sh`) :

| Agent | Profile | Type | Description |
|-------|---------|------|-------------|
| 000 | shadow1 | fort | Super-Master |
| 100 | shadow1 | fort | Master - Coordination |
| 200 | stef1 | fort | Explorer - SPEC creation |
| 201 | octave2 | faible | Doc Generator - PR-DOC |
| 300 | octave2 | faible | Dev Excel |
| 301 | miro2 | faible | Dev Word |
| 302 | miro2 | faible | Dev PPTX |
| 303 | octave2 | faible | Dev PDF |
| 400 | stef1 | fort | Merge - Git fusion |
| 500 | miro1 | fort | Test - Validation |
| 501 | shadow1 | fort | Test Creator - Scripts |
| 502 | stef1 | fort | Test Mapper |
| 600 | octave2 | faible | Release - Publication |

**Règles d'attribution :**
- **Profiles forts (X1)** : Agents de coordination, décision, création complexe
- **Profiles faibles (X2)** : Agents d'exécution répétitive, templates

**Fichier source :** `$BASE/scripts/start-agents.sh`

---

## Commandes Slash (/)

**⚠️ IMPORTANT : Les commandes `/` doivent être sur une ligne SÉPARÉE !**

```
# ❌ MAUVAIS (ne fonctionne pas) :
/clear puis relis ton prompt

# ✅ BON (2 lignes séparées) :
/clear
puis relis ton prompt
```

**En pratique avec Redis :**
```bash
# Envoyer /clear
redis-cli XADD "ma:agent:XXX:inbox" '*' prompt "/clear" from_agent "100" timestamp "$(date +%s)"

# Puis un SECOND message séparé :
redis-cli XADD "ma:agent:XXX:inbox" '*' prompt "relis ton prompt" from_agent "100" timestamp "$(date +%s)"
```

---

*Convention v2.1 - Janvier 2026*
