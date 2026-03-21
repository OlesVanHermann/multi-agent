# x45 — Méthodologie de pipeline auto-améliorante

## Vue d'ensemble

x45 est un mode alternatif du système multi-agent. Au lieu de prompts flat (`.md`), chaque agent utilise **3 fichiers** dans un répertoire dédié :

| Fichier | Rôle | Écrit par |
|---------|------|-----------|
| `system.md` | Contrat immutable (IN/OUT typés) | 945 (Triangle Architect) |
| `memory.md` | Contexte curé pour la tâche en cours | 7XX (Curator) |
| `methodology.md` | Méthodes de travail, améliorées itérativement | 8XX (Coach) |

Le système s'**auto-améliore** via deux boucles de feedback :

- **Boucle courte** : 500 observe → 8XX améliore methodology → 3XX exécute mieux
- **Boucle longue** : 500 observe → 945 réécrit system.md → tous se reconfigurent

## Architecture

Voir [AGENT_X45-ARCHITECTURE.md](AGENT_X45-ARCHITECTURE.md) pour le schéma complet.

```
HUMAN → 900 (Architect) → 945 (Triangle Architect) → écrit tous les system.md
                                    │
     ┌──────────┬──────────────────┼──────────┬──────────┐
     ▼          ▼                  ▼          ▼          ▼
    200        600             7XX pool      500      8XX pool
     │          │                  │          │          │
     ▼          ▼                  ▼          ▼          ▼
 raw → CLEAN → INDEX → memory → 3XX CHAÎNE → OUTPUT
                                                │
                                               500 (observe)
                                                │
                                        ┌───────┴───────┐
                                        ▼               ▼
                                      8XX             945
                                  (methodology)    (system.md)
```

## Le Triangle

Chaque maillon 3XX a son **triangle de support** :

- **3XX** : exécute le process (code, analyse, rédaction...)
- **7XX** : curator — prépare `memory.md` de 3XX (cherche dans l'INDEX)
- **8XX** : coach — améliore `methodology.md` de 3XX (lit les bilans 500)

Voir [AGENT_X45-TEMPLATE-TRIANGLE.md](AGENT_X45-TEMPLATE-TRIANGLE.md) pour le pattern.

## Conventions de numérotation

| Plage | Rôle | Type |
|-------|------|------|
| 900 | Architect Global | Infra (1 seul) |
| 945+ | Triangle Architects | Infra (1 par chaîne) |
| 800 | Coach Global | Infra (1 seul) |
| 8XX | Coaches dédiés | Dédié (1 par 3XX) |
| 7XX | Curators | Dédié (1 par 3XX) |
| 600 | Indexer | Infra (1 seul) |
| 500 | Observer | Infra (1 seul) |
| 3XX | Developers (chaîne) | Workers |
| 200 | Data Prep | Infra (1 seul) |

Voir [AGENT_X45-CONVENTIONS.md](AGENT_X45-CONVENTIONS.md) pour les détails.

## Quick Start

### Nouveau projet x45

```bash
# 1. Cloner multi-agent
git clone <repo> my-project && cd my-project

# 2. Bootstrap x45 (copie templates, crée répertoires)
./scripts/x45-bootstrap.sh

# 3. Mettre les données brutes
cp mes-donnees/* project/raw/

# 4. Configurer l'orientation du projet
$EDITOR prompts/900/memory.md

# 5. Lancer l'infrastructure + Agent 900
./scripts/infra.sh start

# 6. Démarrer le pipeline
./scripts/send.sh 900 "go"          # 900 écrit 945/system.md
./scripts/agent.sh start 945
./scripts/send.sh 945 "go"          # 945 écrit tous les system.md
./scripts/agent.sh start all        # Démarre tous les agents
./scripts/send.sh 200 "go"          # Lance le pipeline (cycle 1)
```

### Ajouter un maillon à la chaîne

```bash
# Crée 343 + 743 (curator) + 843 (coach)
./scripts/x45-add-agent.sh 343 "Vérification qualité"
```

### Voir le prompt assemblé d'un agent

```bash
./scripts/x45-run-agent.sh 345
# Affiche : AGENT.md + system.md + memory.md + methodology.md
```

## Schéma d'exécution (cycles 0-6)

### Cycle 0 — Bootstrap

```
HUMAN écrit prompts/900/memory.md (orientation projet)
  → 900 lit orientation → écrit prompts/945/system.md
  → 945 lit 900's system → écrit tous les system.md (200, 600, 500, 3XX, 7XX, 8XX)
```

### Cycle 1 — Premier passage

```
200 : raw/ → clean/                    (nettoyage données)
600 : clean/ → index/                  (indexation)
7XX : index/ → 3XX/memory.md           (curation)
3XX : exécute avec memory + methodology → pipeline/output
500 : observe outputs → bilans/         (évaluation)
```

Résultat typique : **60-75%** de qualité (les methodology sont génériques).

### Cycles 2-3 — Boucle courte

```
8XX : lit bilans 500 → améliore 3XX/methodology.md
7XX : re-cure memory.md avec les nouvelles infos
3XX : ré-exécute avec methodology améliorée → meilleur output
500 : observe → nouveaux bilans
```

Résultat typique : **82-95%** de qualité.

### Cycles 4-6 — Convergence

```
Si 8XX ne peut plus améliorer → escalade vers 945
945 : réécrit system.md (boucle longue) si nécessaire
Sinon : raffinements mineurs dans methodology
Pipeline se stabilise autour de 95-98%
```

## Différences avec le pipeline standard

| Aspect | Pipeline standard | x45 |
|--------|-------------------|-----|
| Format prompts | `prompts/XXX-nom.md` (flat) | `prompts/XXX/system.md + memory.md + methodology.md` |
| Auto-amélioration | Non | Oui (2 boucles de feedback) |
| Curator dédié | Non | Oui (7XX par 3XX) |
| Coach dédié | Non | Oui (8XX par 3XX) |
| Indexation | Non | Oui (600 + recherche sémantique) |
| Détection mode | Fichiers `.md` dans prompts/ | Répertoires avec `system.md` |
| Agents par worker | 1 | 3 (3XX + 7XX + 8XX) |

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `docs/AGENT_X45-METHODOLOGY.md` | Ce fichier (point d'entrée) |
| `docs/AGENT_X45-ARCHITECTURE.md` | Design système et flux |
| `docs/AGENT_X45-CONVENTIONS.md` | Numérotation et structure |
| `docs/AGENT_X45-TEMPLATE-TRIANGLE.md` | Pattern triangle universel |
| `examples/x45-mcp-libreoffice-calc/` | Exemple complet (15 agents, 6 cycles) |
| `scripts/x45-bootstrap.sh` | Init projet x45 |
| `scripts/x45-run-agent.sh` | Assembler prompt agent |
| `scripts/x45-add-agent.sh` | Créer un triangle |

## Exemple

Voir `examples/x45-mcp-libreoffice-calc/` — un projet complet avec :
- 15 agents (200, 500, 600, 800, 900, 945, 341-345, 741-745, 841-845)
- 6 cycles de feedback
- Progression mesurée : 60% → 82% → 95% → 97% → 98% → 98%
- Output final : serveur MCP Python fonctionnel
