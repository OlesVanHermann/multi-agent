# 170 — Reference : Explorer l'agent 345 createur

## Principe

Le z21 cree par 170 est un agent de **maintenance/patching** sur du code **deja developpe** par un agent `345-cree-{nom}` (ou equivalent x45). Avant de creer les sous-contextes, il faut comprendre parfaitement ce qui a ete construit, pourquoi, et comment.

---

## Identifier l'agent createur

### Recherche automatique

```bash
# Trouver l'agent 345 ou x45 qui a cree le service
ls prompts/ | grep -iE "(345|3[0-9]{2}).*cree|create.*{service}"

# Trouver dans les pool-requests les taches liees
ls pool-requests/done/ | grep -i "{service}"

# Chercher dans les history files
grep -rl "{service}" prompts/*//*.history 2>/dev/null
```

### Si pas de 345 explicite

Le code peut avoir ete cree par un agent x45 (ex: `prompts/345-cree-search/`) ou par un pipeline plus ancien. Chercher :
1. `prompts/3XX-cree-*/` — agents createurs standard
2. `prompts/3XX-*/system.md` — tout agent 3XX lie au service
3. `pool-requests/done/` — specs terminees qui ont genere le code
4. `git log --oneline -- {repertoire_projet}/backend/*{service}*` — qui a commite le code

---

## Quoi explorer dans l'agent createur

### Fichiers a lire (par ordre de priorite)

| Fichier | Ce qu'il apporte |
|---------|-----------------|
| `system.md` | Plan de developpement, scope, architecture prevue |
| `memory.md` | Ce qui a ete REELLEMENT construit, bugs rencontres, iterations |
| `methodology.md` | Contraintes de dev appliquees, patterns specifiques |
| `*.history` | **CRITIQUE** — log d'execution reel, requirements user non documentes ailleurs |
| `pool-requests/specs/*.md` | Specifications detaillees des features |
| `pool-requests/done/*.md` | Taches completees — scope exact de ce qui est fait |

### Informations a extraire

1. **Plan prevu vs realite** :
   - Quelles features etaient prevues ?
   - Lesquelles ont ete reellement implementees ?
   - Lesquelles sont partielles ou manquantes ?

2. **Decisions d'architecture** :
   - Pourquoi tel pattern a ete choisi ?
   - Quelles alternatives ont ete rejetees ?
   - Quels compromis ont ete faits ?

3. **Bugs et regressions** :
   - Quels bugs ont ete rencontres pendant le dev ?
   - Lesquels ont ete corriges ? Lesquels persistent ?
   - Quels patterns de bugs se repetent ?

4. **Requirements user** (dans les .history) :
   - Demandes explicites de l'utilisateur
   - Corrections de direction pendant le dev
   - Priorites et contraintes non ecrites

---

## Mapper le plan 345 vers les sous-contextes z21

### Methode

Le plan du 345 est organise en taches sequentielles (plan-TODO/plan-DONE). Les sous-contextes z21 sont organises par **domaine fonctionnel**. Le mapping n'est PAS 1:1.

```
Plan 345 (sequentiel)          →  Contextes z21 (fonctionnel)
┌────────────────────┐           ┌──────────────────────┐
│ 01-setup-schema    │ ────────→ │ b-schema             │
│ 02-crud-endpoints  │ ─┬──────→ │ b-crud               │
│ 03-search          │  │  ┌───→ │ b-search             │
│ 04-auth-perms      │ ─┼──┤     │ b-auth               │
│ 05-frontend-list   │  │  └───→ │ f-list-panel         │
│ 06-frontend-detail │ ─┘ ────→  │ f-detail-view        │
└────────────────────┘           └──────────────────────┘
```

### Regles de mapping

1. **Plusieurs taches 345 → 1 contexte z21** : si 3 taches 345 touchent le meme endpoint group, elles deviennent 1 contexte
2. **1 tache 345 → plusieurs contextes z21** : si 1 tache 345 couvre backend + frontend, elle se split en `b-*` + `f-*`
3. **Taches 345 non implementees** : ne PAS creer de contexte z21 pour du code qui n'existe pas encore — le z21 patche l'existant
4. **Taches 345 partielles** : creer le contexte z21 avec une note `[PARTIEL]` dans archi.md — le z21 completera

### Enrichir avec l'exploration code

L'Agent 0 (345) fournit le **pourquoi** et le **plan**. Les Agents 1-2 (code + bilans) fournissent le **quoi** (code reel). Croiser :

- Feature prevue par 345 + code reel → contexte avec archi.md precis
- Feature prevue par 345 + code absent → PAS de contexte (ou contexte marque `[A_CREER]`)
- Code reel sans feature 345 → code orphelin, creer un contexte quand meme

---

## Prompt Agent 0 (a copier dans Phase 1)

```
Explore thoroughly the creator agent for {service} in $BASE/prompts/.
1. Find the 345/3XX agent directory that created {service} (e.g. prompts/345-cree-{service}/)
2. Read system.md — understand the development plan, architecture decisions, scope
3. Read memory.md — understand what was built, bugs encountered, iterations
4. Read methodology.md — understand the dev patterns and constraints applied
5. Read *.history files — these contain the ACTUAL execution log and user requirements
6. Read any SPEC files referenced (pool-requests/specs/)
7. Check pool-requests/done/ for completed tasks related to {service}
Give me: the complete development plan, what was actually built vs planned, all architecture decisions, bugs encountered during development, user requirements from history files, and the final state of the code.
```

---

## Checklist post-exploration 345

Avant de passer a la Phase 1.5 (proposition user), verifier :

- [ ] Agent createur identifie (ID + type + repertoire)
- [ ] Plan prevu lu et compris
- [ ] Features reellement implementees listees
- [ ] Ecarts plan/code documentes
- [ ] Bugs connus du dev initial notes
- [ ] Requirements user extraits des .history
- [ ] Decisions d'architecture comprises (pas juste le code, le POURQUOI)
