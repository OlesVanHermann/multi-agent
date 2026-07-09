# 160 — Reference : Template de Specification

## Format standard d'une spec tache

Chaque spec est un fichier markdown dans le repertoire de la tache.
Toutes les sections ne sont pas obligatoires — adapter selon le domaine.

```markdown
# {NN} — {Titre de la tache}

## Objectif
{1-3 phrases claires decrivant ce que la tache doit accomplir}

## Approche
{Methode ou strategie technique — optionnel si evidente}

## Sources / Details
{Tableau, liste ou description des inputs :}
| Source | Type | Details |
|--------|------|---------|
| ... | ... | ... |

## Script source
`sources/{NN}_{script}.sh`

## Config
`sources/{config_file}`

## Documentation
`sources/{NN}_{DOC}.md`

## Commande
```bash
{Commande principale a executer}
```

## Parametres / Hyperparametres
{Tableau des parametres cles :}
| Parametre | Valeur | Raison |
|-----------|--------|--------|
| ... | ... | ... |

## Duree estimee
{Estimation : ~15 minutes, 6-12 heures, etc.}

## Criteres de succes
- [ ] {Critere 1 verifiable}
- [ ] {Critere 2 verifiable}
- [ ] {Critere 3 verifiable}
- [ ] {Critere N verifiable}

## Prerequis
- {Etape XX completee}
- {Outil/lib installe}

## Fichiers de sortie
- {fichier1}
- {fichier2}
```

---

## Regles pour ecrire une bonne spec

### Objectif
- UNE tache = UN objectif clair
- Verifiable : on peut repondre oui/non "est-ce fait ?"
- Pas de "et aussi" — si c'est deux choses, c'est deux taches

### Criteres de succes
- Toujours en checkbox `- [ ]` pour tracking
- CONCRETS et VERIFIABLES (pas "code propre" mais "tests passent")
- Minimum 3 criteres, maximum 10
- Inclure les verifications automatiques quand possible :
  ```
  - [ ] Exit code 0
  - [ ] Fichier output existe et taille > 0
  - [ ] Test unitaire passe
  ```

### Commande
- Commande EXECUTABLE telle quelle (pas de pseudo-code)
- Variables clairement identifiees : `${INPUT_DIR}`, `${OUTPUT_DIR}`
- Si plusieurs etapes, les numeroter

### Prerequis
- Toujours expliciter les dependances vers d'autres etapes
- Format : "Etape {NN} completee" avec le numero
- Mentionner les outils/libs necessaires

### Duree estimee
- Estimation realiste, pas optimiste
- Indiquer si c'est du temps machine (training GPU) ou humain

### Sources
- Le repertoire `sources/` contient les scripts et docs de reference
- Convention : `{NN}_{nom}.sh` pour les scripts
- Convention : `{NN}_{NOM_DOC}.md` pour la doc de reference
- Copier/extraire les parties pertinentes de la doc source du projet

---

## Exemples reels adaptes par domaine

### Domaine : ML/Training
```markdown
## Criteres de succes
- [ ] Training termine sans erreur (exit code 0)
- [ ] Checkpoint best existe et taille > 0
- [ ] Loss finale convergee (val_loss stable)
- [ ] Pas de NaN/Inf dans les logs
- [ ] TensorBoard logs presents
```

### Domaine : Backend API
```markdown
## Criteres de succes
- [ ] Endpoint repond 200 OK
- [ ] Schema JSON respecte (validation Pydantic)
- [ ] Tests pytest passent (100%)
- [ ] Pas de regression sur endpoints existants
- [ ] CHANGES.md avec instructions d'integration
```

### Domaine : Frontend
```markdown
## Criteres de succes
- [ ] Composant render sans erreur
- [ ] Props typees (TypeScript strict)
- [ ] Responsive (mobile + desktop)
- [ ] Hook connecte au backend
- [ ] Pas d'erreur console
```

### Domaine : Infrastructure / DevOps
```markdown
## Criteres de succes
- [ ] Service demarre sans erreur
- [ ] Health check repond OK
- [ ] Ports corrects et pas de conflit
- [ ] Logs structures (JSON)
- [ ] Rollback teste
```

### Domaine : Data Pipeline
```markdown
## Criteres de succes
- [ ] Tous les fichiers telecharges (count correct)
- [ ] Format unifie (format cible respecte)
- [ ] Pas de fichiers corrompus (validation)
- [ ] Destination correcte
- [ ] Stats produites (count, min/max/avg)
```

---

## Granularite des taches

### Trop grosse (a decouper)
```
# MAUVAIS — "Implementer le module complet"
→ Decouper en sous-taches autonomes avec input/output clairs
```

### Trop petite (a fusionner)
```
# MAUVAIS — "Ajouter import os"
→ Fusionner dans la tache qui en a besoin
```

### Bonne granularite
```
# BON — 1 endpoint + tests + frontend hook
# BON — 1 script de traitement avec input/output clairs
# BON — 1 config + verification
# Cible : 15 min - 12h de travail agent
```
