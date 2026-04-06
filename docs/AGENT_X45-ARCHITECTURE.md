# Architecture Multi-Agent x45

## Principe fondamental

Tout agent = system.md + memory.md + methodology.md

- **system.md** : contrat immutable. Ce que l'agent fait. IN/OUT typés.
- **memory.md** : contexte curé. Les informations nécessaires à la tâche en cours.
- **methodology.md** : méthodes de travail. Comment exécuter le contrat avec le contexte.

## Schéma global

```
                              HUMAN
                                │
                                ▼
                              900
                                │
                                ▼
                              945
                                │
     ┌──────────┬───────────────┼───────────┬──────────┐
     ▼          ▼               ▼           ▼          ▼
    200        600          7XX pool       500      8XX pool
     │          │               │           │          │
     ▼          ▼               ▼           ▼          ▼
 raw ──► CLEAN ──► INDEX ──► memory ──► 3XX CHAÎNE ──► OUTPUT
                                                        │
                                                       500
                                                        │
                                                ┌───────┴───────┐
                                                ▼               ▼
                                              8XX             945
                                          boucle courte   boucle longue
```

## Le process principal (3XX)

Les 3XX forment une chaîne séquentielle. L'OUTPUT d'un maillon est l'INPUT du suivant.
Le seul OUTPUT qui compte est celui du dernier maillon.

```
 INPUT ──► 341 ──► 342 ──► 343 ──► ... ──► 3XX ──► OUTPUT FINAL
```

Tous les autres agents existent pour soutenir cette chaîne.

## Deux types d'agents

### Infra partagée (scalent peu)
| Agent | Rôle | Quantité |
|-------|------|----------|
| 900 | Architect global | 1 |
| 945 | Triangle Architect | 1 |
| 200 | Data Prep | 1 |
| 600 | Indexer | 1 |
| 500 | Observer | 1 |
| 800 | Coach global | 1 |

### Dédiés (scalent avec les 3XX)
| Agent | Rôle | Quantité |
|-------|------|----------|
| 7XX | Curator pour 3XX | ×N |
| 8XX | Coach pour 3XX | ×N |
| 3XX | Developers (chaîne) | ×N |

**Total pour 100 workers : 6 + 300 = 306 agents**

## Deux boucles de feedback

### Boucle courte
```
500 observe ──► 8XX améliore methodology ──► 3XX exécute mieux
```
La méthode change, le contrat reste.

### Boucle longue
```
500 observe ──► 945 réécrit system.md ──► tous les agents se reconfigurent
```
Le contrat change, tout se reconfigure. Activée quand la boucle courte ne suffit plus.

## Flux de données

```
raw ──► 200 ──► clean data ──► 600 ──► INDEX ──► 7XX ──► memory ──► 3XX
        format     .md         index   vectors   filtre   curé      exécute
```

Chaque étape a un rôle précis :
- 200 : le format (brut → markdown propre)
- 600 : la recherche (markdown → vecteurs cherchables)
- 7XX : la sélection (cherche → contexte curé pour 3XX)

## Qui écrit quoi

| Fichier | Écrit par | Quand |
|---------|-----------|-------|
| *-system.md | 945 | Au setup + boucle longue |
| *-memory.md | 7XX | En continu, à chaque tâche |
| *-methodology.md | 8XX | Après chaque cycle |
| 945-system.md | 900 | Au setup |
| 900-system.md | HUMAN | Une fois |
