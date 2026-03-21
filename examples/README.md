# Exemples

5 exemples gradués, couvrant les 3 types d'agents : MONO, X45, Z21.

---

## Vue d'ensemble

| # | Exemple | Mode | Agents | But |
|---|---------|------|--------|-----|
| 1 | [1-mono-simple](1-mono-simple/) | MONO | 3 | Format de base : Architect + Master + Dev |
| 2 | [2-mono-complet](2-mono-complet/) | MONO | 10 | Hiérarchie complète : Architect → Release |
| 3 | [3-x45-simple](3-x45-simple/) | X45 | 7 | 1 triangle (3XX+7XX+8XX) avec feedback |
| 4 | [4-x45-complet](4-x45-complet/) | X45 | 15 | 3 triangles, 3 cycles, 60% → 95% |
| 5 | [5-z21-simple](5-z21-simple/) | Z21 | 6 | 6 agents spécialisés sur 3 sous-contextes |

---

## MONO (un fichier par agent)

Un fichier `.md` par agent dans son répertoire. Pas de feedback automatique.

### 1. [1-mono-simple](1-mono-simple/) — 3 agents

Le minimum : Architect + Master + Developer.

```
prompts/
  000-architect/000-architect.md
  100-master/100-master.md
  300-dev/300-dev.md
```

### 2. [2-mono-complet](2-mono-complet/) — 10 agents

Toute la hiérarchie :

```
000 Architect → 010 Super-Master → 200 Explorer → 100 Master
                                                       │
                                               ┌───────┼───────┐
                                              300     301     302
                                               └───────┼───────┘
                                                       │
                                              400 Integrator → 500 Tester → 600 Releaser
```

---

## X45 (triangle system/memory/methodology)

3 fichiers par agent. Feedback automatique via Coach + Curator.

### 3. [3-x45-simple](3-x45-simple/) — 7 agents, 1 triangle

Pattern central de X45 :

```
741 Curator  → 341/memory.md        (prépare le contexte)
841 Coach    → 341/methodology.md   (améliore la méthode)
500 Observer → bilans/              (évalue les outputs)
```

Tâche : analyser un CSV de ventes. Montre la boucle de feedback complète.

### 4. [4-x45-complet](4-x45-complet/) — 15 agents, 3 triangles

Projet réel : serveur MCP Python pour LibreOffice Calc.
3 workers chaînés (341→342→345), chacun avec son triangle.
Progression de 60% à 95% sur 3 cycles.

---

## Z21 (6 agents + sous-contextes)

6 agents spécialisés (Master, Dev, Tester, Reviewer, Coach, Architect) partageant N sous-contextes. Chaque sous-contexte a son `archi.md` + `memory.md` + `methodology.md`.

### 5. [5-z21-simple](5-z21-simple/) — 6 agents, 3 sous-contextes

Service API : backend users, backend items, frontend React.

```
prompts/370-api/
├── 370-170  Master (routeur vers b-users, b-items, f-app)
├── 370-370  Developer
├── 370-570  Tester
├── 370-770  Reviewer
├── 370-870  Coach
├── 370-970  Architect
├── b-users/ (archi + memory + methodology)
├── b-items/ (archi + memory + methodology)
└── f-app/   (archi + memory + methodology)
```

---

## Comparaison des 3 modes

| | MONO | X45 | Z21 |
|--|------|-----|-----|
| Format | `prompts/XXX-nom/XXX-nom.md` | `prompts/XXX/{system,memory,methodology}.md` | 6 agents + sous-contextes |
| Feedback | Non | Oui (boucle courte + longue) | Oui (par sous-contexte) |
| Scaling | 1 agent = 1 rôle | 1 triangle = 1 worker | 6 agents = N zones |
| Cas d'usage | Tâches simples | Tâches itératives | Services multi-zones |

## Parcours recommandé

1. **Découvrir le format** → `1-mono-simple`
2. **Comprendre la hiérarchie** → `2-mono-complet`
3. **Découvrir X45 et le feedback** → `3-x45-simple`
4. **Voir un projet réel X45** → `4-x45-complet`
5. **Découvrir Z21** → `5-z21-simple`

## Documentation

| Doc | Contenu |
|-----|---------|
| [`docs/AGENT_MONO.md`](../docs/AGENT_MONO.md) | Format MONO, structure répertoire |
| [`docs/AGENT_X45-METHODOLOGY.md`](../docs/AGENT_X45-METHODOLOGY.md) | Mode X45, boucles de feedback |
| [`docs/AGENT_Z21-METHODOLOGY.md`](../docs/AGENT_Z21-METHODOLOGY.md) | Mode Z21, sous-contextes |
