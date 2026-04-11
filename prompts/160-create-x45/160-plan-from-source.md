# 160 — Reference : Creer un Plan depuis la Documentation Source

## Principe

Un plan se cree en 4 etapes :
1. **COLLECTER** — lire toute la doc source disponible
2. **CATEGORISER** — identifier les grandes phases/domaines
3. **DECOUPER** — creer des taches atomiques
4. **GENERER** — ecrire les specs + creer l'arborescence

---

## Etape 1 : COLLECTER

### Types de sources

| Source | Ou la trouver | Ce qu'elle apporte |
|--------|--------------|-------------------|
| CAHIER_DES_CHARGES.md | Racine du projet | Vision globale, features, contraintes |
| RECAP.md | Racine du projet | Etat des lieux, ce qui existe deja |
| README-pipeline.md | Racine du projet | Architecture technique, modules, stack |
| CLAUDE.md | Racine du projet | Conventions, workflow, regles du projet |
| docs/*.md | docs/ | Documentation technique detaillee |
| Video analysis | Docs de reference | Features extraites de demos/screencasts |
| Code existant | Repertoire projet | Ce qui est deja implemente |
| configs/ | configs/ | Fichiers de configuration existants |
| scripts/ | scripts/ | Scripts existants a integrer dans le plan |

### Ordre de lecture

1. RECAP.md ou README-pipeline.md (vue d'ensemble rapide)
2. CAHIER_DES_CHARGES.md (vision complete)
3. docs/ (details techniques)
4. Code existant (ce qui est fait vs ce qui manque)

---

## Etape 2 : CATEGORISER

### Methode

Lire le CAHIER_DES_CHARGES et identifier les grandes phases ou domaines.

#### Pour un pipeline lineaire (ML, build, deploy)
Les categories suivent l'ordre du pipeline :
```
A-setup       → Prerequis, environnement
B-data        → Acquisition, validation, preparation
C-process     → Traitement principal
D-export      → Export, packaging, livraison
E-verify      → Verification, evaluation, QA
```

#### Pour un projet feature-by-feature (SaaS, app)
Les categories suivent les domaines fonctionnels :
```
A-core          → Fonctionnalites de base du domaine principal
B-secondary     → Module secondaire
C-integrations  → Integrations tierces
D-security      → Securite, permissions
...
```

#### Pour un projet multi-composants (microservices, monorepo)
Les categories suivent les composants :
```
A-api           → Point d'entree / API
B-auth          → Authentification
C-workers       → Services de traitement
D-frontend      → Interface web
E-deploy        → Infrastructure, CI/CD
```

### Regle de decision du nombre de categories
- Pipeline < 20 taches : 3-5 categories
- Projet medium 20-100 taches : 5-10 categories
- Gros projet > 100 taches : 10-20 categories
- Max 26 (A-Z)

---

## Etape 3 : DECOUPER

### Identifier les taches depuis la doc source

Pour chaque section du CAHIER_DES_CHARGES :
1. Est-ce une tache autonome ? (input clair → output clair)
2. Est-ce trop gros ? (> 12h de travail agent → decouper)
3. Est-ce trop petit ? (< 15 min → fusionner avec une voisine)
4. Quelle est sa categorie ?
5. Quels sont ses prerequis ?

### Numerotation

```
01, 02, 03, ... 10, 11, ...    # Sequentiel global
04b, 04c                        # Variantes d'une meme etape
```

La numerotation est GLOBALE (pas par categorie) et suit l'ordre d'execution.

### Graphe de dependances

Construire mentalement le graphe :
```
01 → 02 → 03 → 04
              → 04b     # Parallele avec 04
         → 05 → 06
              → 07      # Parallele avec 06
         08 → 09 → 10
```

Les taches sans dependance entre elles peuvent etre executees en parallele par des triangles x45 differents.

---

## Etape 4 : GENERER

### Pour chaque tache identifiee

1. **Creer le repertoire** :
```bash
mkdir -p {repertoire_projet}/plan-TODO/{categorie}/{NN}-{nom}/sources
mkdir -p {repertoire_projet}/plan-TODO/{categorie}/{NN}-{nom}/bilans
mkdir -p {repertoire_projet}/plan-TODO/{categorie}/{NN}-{nom}/output
```

2. **Ecrire la spec** `{NN}-{nom}.md` (voir `160-spec-template.md`)

3. **Copier les sources pertinentes** dans `sources/` :
   - Extraire la section du CAHIER_DES_CHARGES qui concerne cette tache
   - Copier les scripts existants mentionnes
   - Copier les configs referencees
   - Copier la doc technique pertinente

4. **Creer la structure miroir** plan-DOING et plan-DONE :
```bash
for cat in $(ls {repertoire_projet}/plan-TODO/); do
  mkdir -p {repertoire_projet}/plan-DOING/$cat
  mkdir -p {repertoire_projet}/plan-DONE/$cat
done
```

---

## Exemples de derivation par type de source

### Depuis un CAHIER_DES_CHARGES technique (pipeline lineaire)

**Methode** : Chaque grande section du cahier → 1 categorie, chaque etape → 1 tache

```
CAHIER_DES_CHARGES section "Prerequis"    → A-setup/    → 01-setup-env
CAHIER_DES_CHARGES section "Donnees"      → B-data/     → 02-acquire, 03-transform, 04-validate
CAHIER_DES_CHARGES section "Traitement"   → C-process/  → 05-run-main, 06-run-alt
CAHIER_DES_CHARGES section "Livraison"    → D-export/   → 07-export, 08-optimize
CAHIER_DES_CHARGES section "Validation"   → E-verify/   → 09-benchmark
```

### Depuis un RECAP fonctionnel (projet existant a completer)

**Methode** : La section "ce qui manque" → 1 tache par feature manquante

```
RECAP section "Ce qui MANQUE"
  → "Feature A"  → A-core/xx-feature-a/
  → "Feature B"  → A-core/xx-feature-b/
  → "Module X"   → B-secondary/xx-module-x/
```

### Depuis une video/screencast

**Methode** : Transcrire, lister, categoriser, generer

```
1. Transcrire/analyser la video → ANALYSE_VIDEO.md
2. Lister chaque feature visible → liste brute
3. Categoriser par domaine fonctionnel
4. Creer 1 spec par feature
```

---

## Checklist finale

Apres generation du plan, verifier :

- [ ] Chaque tache a une spec `.md` dans son repertoire
- [ ] Chaque spec a un Objectif, des Criteres de succes, et des Prerequis
- [ ] Les categories couvrent tout le CAHIER_DES_CHARGES
- [ ] Aucune tache orpheline (sans categorie)
- [ ] Les prerequis forment un graphe coherent (pas de cycle)
- [ ] plan-DOING/ et plan-DONE/ ont les memes sous-categories que plan-TODO/
- [ ] Les numerotations sont uniques et sequentielles
- [ ] Les sources pertinentes sont copiees dans sources/ de chaque tache
