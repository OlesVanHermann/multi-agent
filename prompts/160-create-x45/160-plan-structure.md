# 160 — Reference : Structure des Plans

## Emplacement des plans

Les plans sont dans `$BASE/plans/{nom-projet}/` (pas dans docs/).
Exemples : `plans/train-model/`, `plans/mail/`, `plans/visio/`, `plans/edition/`

## Organisation des repertoires

```
plans/{nom-projet}/
├── plan-TODO/          # Taches a faire (le backlog)
│   ├── A-{categorie}/  # Categorie A
│   │   └── {NN}-{nom-tache}/
│   │       ├── {NN}-{nom-tache}.md    # Spec de la tache
│   │       ├── sources/                # Scripts, docs de reference
│   │       ├── bilans/                 # Rapports Observer (vide au debut)
│   │       └── output/                 # Output Dev (vide au debut)
│   ├── B-{categorie}/
│   └── ...
├── plan-DOING/         # Tache en cours (1 seule a la fois par triangle)
│   ├── A-{categorie}/  # Meme structure vide au debut
│   ├── B-{categorie}/
│   └── ...
├── plan-DONE/          # Taches terminees
│   ├── A-{categorie}/
│   │   └── {NN}-{nom-tache}.md          # Spec deplacee ici apres completion
│   │   └── {NN}-{nom-tache}-output/     # Output copie ici
│   └── ...
└── plan-FIX/           # (optionnel) Taches a corriger
```

## Convention de nommage des categories

Lettre unique + nom descriptif, en ordre logique de pipeline :

| Lettre | Usage type | Exemples |
|--------|-----------|----------|
| A | Setup / prerequis | `A-setup`, `A-core` |
| B | Donnees / preparation | `B-data`, `B-secondary` |
| C | Traitement principal | `C-process`, `C-integrations` |
| D | Export / livraison | `D-export`, `D-security` |
| E | Verification / benchmark | `E-verify` |
| F-Z | Selon le domaine | `F-docs`, `G-deploy` |

**Regles :**
- Ordre alphabetique = ordre d'execution logique
- Max 10-15 categories par projet (au-dela, regrouper)
- Noms en minuscules avec tirets : `A-setup`, pas `A_Setup`

## Convention de nommage des taches

Format : `{NN}-{nom-descriptif}` ou `{NNx}-{variante}`

```
01-setup-environment
02-acquire-data
03-transform-data
04-validate-output
04b-validate-secondary         # Variante avec lettre suffixe
05-prepare-format
06-process-main
07-process-alt
```

**Regles :**
- Numerotation sequentielle dans tout le projet (pas par categorie)
- Variantes avec suffixe lettre : `04b`, `02c`
- Noms en minuscules avec tirets
- Noms courts mais descriptifs (3-5 mots max)

## Structure d'une tache

Chaque tache = 1 repertoire avec :

```
{NN}-{nom-tache}/
├── {NN}-{nom-tache}.md     # Spec (OBLIGATOIRE)
├── sources/                 # Scripts et docs de reference (optionnel)
│   ├── {NN}_{script}.sh    # Script executable
│   ├── {NN}_{DOC}.md       # Documentation de reference
│   └── ...
├── bilans/                  # Rapports Observer (cree vide)
└── output/                  # Output Dev (cree vide)
```

## Prerequis plan-DOING et plan-DONE

Les sous-repertoires de categories doivent exister dans plan-DOING et plan-DONE meme s'ils sont vides :

```bash
# Creer la structure miroir
for cat in $(ls {repertoire_projet}/plan-TODO/); do
  mkdir -p {repertoire_projet}/plan-DOING/$cat
  mkdir -p {repertoire_projet}/plan-DONE/$cat
done
```

## Exemples de structures

### Pipeline lineaire (~10 taches)
```
plan-TODO/
├── A-setup/     → 01-setup-env
├── B-data/      → 02-acquire, 03-transform, 04-validate, 05-prepare
├── C-process/   → 06-run-main, 07-run-alt
├── D-export/    → 08-export, 09-optimize
└── E-verify/    → 10-benchmark
```

### Projet feature-by-feature (100+ taches)
```
plan-TODO/
├── A-core/
│   └── 01-feature-alpha/
│       └── sources/
├── B-secondary/
├── C-integrations/
├── ...
└── N-admin/
```

### Projet multi-composants
```
plan-TODO/
├── A-api/
├── B-auth/
├── C-frontend/
├── D-workers/
└── E-deploy/
```

## Quand creer un plan-FIX

plan-FIX est optionnel. L'utiliser quand :
- Un Observer score < 50 apres 6 cycles
- Un bug est decouvert dans une tache DONE
- Le Master escalade une tache problematique
