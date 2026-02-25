# Exemples

4 exemples gradués, du plus simple au plus complexe.

---

## Vue d'ensemble

| # | Exemple | Mode | Agents | But |
|---|---------|------|--------|-----|
| 1 | [1-pipeline-simple](1-pipeline-simple/) | pipeline | 3 | Format de base : 1 fichier flat par agent |
| 2 | [2-pipeline-complet](2-pipeline-complet/) | pipeline | 10 | Hiérarchie complète : Architect → Release |
| 3 | [3-x45-simple](3-x45-simple/) | x45 | 7 | 1 triangle (3XX+7XX+8XX) avec feedback |
| 4 | [4-x45-complet](4-x45-complet/) | x45 | 15 | 3 triangles, 3 cycles, 60% → 95% |

---

## Pipeline standard (mode flat)

Un fichier `.md` par agent. Pas de feedback automatique.

### 1. [1-pipeline-simple](1-pipeline-simple/) — 3 agents

Le minimum : Architect + Master + Developer avec le workflow Pool Requests.

```
prompts/
  000-architect.md    ← configure, supervise
  100-master.md       ← dispatch
  300-dev.md          ← implémente
```

### 2. [2-pipeline-complet](2-pipeline-complet/) — 10 agents

Toute la hiérarchie du pipeline standard :

```
000 Architect → 200 Explorer → 100 Master
                                  │
                            ┌─────┼─────┐
                           300   301   302  (en parallèle)
                            └─────┼─────┘
                                  │
                           400 Integrator → 500 Tester → 600 Releaser
```

---

## x45 (mode triangle)

3 fichiers par agent (`system.md` + `memory.md` + `methodology.md`). Feedback automatique via Observer + Coach.

### 3. [3-x45-simple](3-x45-simple/) — 7 agents, 1 triangle

Le pattern central de x45 :

```
741 Curator  → 341/memory.md       (prépare le contexte)
841 Coach    → 341/methodology.md   (améliore la méthode)
500 Observer → bilans/              (évalue les outputs)
```

Tâche : analyser un CSV de ventes. Montre la boucle de feedback complète.

### 4. [4-x45-complet](4-x45-complet/) — 15 agents, 3 triangles

Projet réel : serveur MCP Python pour LibreOffice Calc.
3 workers chaînés (341→342→345), chacun avec son triangle.
Progression de 60% à 95% sur 3 cycles.

---

## Deux modes de pipeline

Le système supporte deux modes, détectés automatiquement :

| | Pipeline standard | x45 |
|--|-------------------|-----|
| Format | `prompts/XXX-nom.md` | `prompts/XXX/{system,memory,methodology}.md` |
| Feedback | Non | Oui (boucle courte + longue) |
| Amélioration | Manuelle | Automatique (Coach + Curator) |
| Cas d'usage | Tâches simples, parallélisables | Tâches complexes, itératives |

## Parcours recommandé

1. **Découvrir le format** → `1-pipeline-simple`
2. **Comprendre la hiérarchie** → `2-pipeline-complet`
3. **Découvrir x45 et le feedback** → `3-x45-simple`
4. **Voir un projet réel** → `4-x45-complet`

Pour en savoir plus sur x45 : [`docs/X45-METHODOLOGY.md`](../docs/X45-METHODOLOGY.md)
