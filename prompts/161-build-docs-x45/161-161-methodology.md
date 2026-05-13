# 161-161 Methodology — Creation de specs

## Cycle de travail

### Mode BATCH (creer toutes les specs d'un service)
1. Lister les sources : `ls ~/docs/{service}/plan/`
2. Pour chaque categorie non couverte par plan-TODO ou plan-DONE :
   a. Curator lit les sources vendor (.txt)
   b. Dev (Master) ecrit CHANGES.md dans plan-TODO/{CAT}/{level}/{feature}/
   c. Observer evalue
   d. Si score < 98 : Coach ameliore → retry

### Mode SINGLE (ajouter une feature)
1. Identifier la categorie
2. Curator lit le contexte
3. Dev ecrit la spec
4. Observer evalue

## Regles

### Structure de repertoire
- `{LETTRE}-{categorie}/` : ex A-file-management
- `{CHIFFRE}-{sous-categorie}/` : ex 0-albums
- `{LETTRE}-{feature}/` : ex a-create-album
- Chaque feature contient au minimum CHANGES.md

### Contenu obligatoire dans CHANGES.md

Structure minimale acceptee :

```markdown
# {feature-name}

## Resume
{2-3 phrases decrivant ce que fait la feature, pourquoi, et quel probleme elle resout}

## Backend
### Models

**Regle absolue** : tout model cite dans le tableau "Files produced" DOIT etre detaille ici avec ses champs. Zéro exception. Si tu ecris `backup_models.py — 8 models`, alors 8 models doivent avoir leurs champs listes ci-dessous.

- `{ModelName}` : {champs cles avec types} — `{table_pg}`

### Endpoints
- `POST /api/{resource}/` : creer {resource} — body: `{champs}` — response: `{schema}`
- `GET /api/{resource}/{id}` : lire — response: `{schema}`
- `PATCH /api/{resource}/{id}` : modifier — body: `{champs modifiables}`
- `DELETE /api/{resource}/{id}` : supprimer — response: `204`

### Dependencies
- Services : {liste}
- Auth : `Depends(get_current_user)` obligatoire sur tous les endpoints

## Frontend
### Components
- `{ComponentName}` (src/components/{path}.jsx) : {role}, props: `{liste props}`

### Hooks
- `use{Name}` (src/hooks/{name}.ts) : {ce qu il fait}, retourne: `{liste valeurs}`

### API calls
- `{nomFonction}(params)` → `{methode} {path}` — dans src/api/{service}.ts

## Tests
- Minimum 3 tests unitaires backend (pytest)
- Minimum 2 tests integration (happy path + error case)
- Scenarios :
  - `test_{feature}_creates_correctly` : creer avec donnees valides → 201
  - `test_{feature}_requires_auth` : sans token → 401
  - `test_{feature}_validates_input` : donnees invalides → 422

## Criteres d'acceptation
- [ ] L'utilisateur peut {action principale}
- [ ] Sans authentification, l'action echoue avec 401
- [ ] Les donnees sont persistees en base
- [ ] Le frontend affiche {resultat attendu}
- [ ] Les tests passent sans mock de la DB
```

### Depuis les sources vendor
- Lire les .txt dans ~/docs/{service}/plan/{category}/
- Extraire les features, endpoints, UI patterns
- Adapter au stack aiapp (FastAPI, React, PG, S3)
- Ne PAS copier les textes vendor — synthetiser
- Chaque source donne au minimum : 1 endpoint concret, 1 model, 1 scenario de test

### Anti-doublon
- Avant de creer une feature : verifier plan-TODO + plan-DONE
- `find ~/docs/{service}/plan-TODO ~/docs/{service}/plan-DONE -name "*{keyword}*"`
- Si doublon partiel : consolider dans la spec existante, ne pas creer une nouvelle

### Checklist de validation AVANT soumission (obligatoire)

Avant d'ecrire le CHANGES.md final, verifier :

```
[ ] Section "## Criteres d'acceptation" presente avec >= 4 items checkbox [ ]
[ ] `Depends(get_current_user)` cite dans section Dependencies ou dans les endpoints
[ ] Au moins 2 endpoints avec methode HTTP + path + description
[ ] Au moins 1 test_*_requires_auth → 401 dans les scenarios
[ ] Si critere d'acceptation contient "403" ou "non-admin" → test_*_admin_role_check present
[ ] COHERENCE tests/criteres : chaque critere auth dans "## Criteres d'acceptation" a son test
[ ] Aucun placeholder non rempli ({resource}, {schema}, {liste}) dans le texte final
[ ] COHERENCE : chaque model cite dans "Files produced" est detaille dans "### Models"
```

Si un item manque → completer AVANT de signaler done.

### Criteres de qualite minimum (score Observer)
- Resume present et comprehensible : +10
- Au moins 2 endpoints avec methode HTTP + path + body + response : +25
- Au moins 1 component frontend nomme avec props : +15
- Au moins 3 scenarios de test nommes : +20
- Criteres d'acceptation en checklist (min 4) : +20
- Dependencies auth (`Depends(get_current_user)`) mentionnees : +10
- **Total 100. Score >= 90 pour passer en DONE.**

### Format acceptable pour les endpoints

Deux formats sont valides :

**Format bullet :**
```
- `POST /api/{resource}/` : creer {resource} — body: `{champs}` — response: `{schema}`
```

**Format tableau (prefere pour specs longues) :**
```
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/{resource}/ | creer {resource} — body: {champs} — response: {schema} |
```

Le format tableau est prefere quand il y a >= 5 endpoints. Dans tous les cas : methode + path + description obligatoires.
