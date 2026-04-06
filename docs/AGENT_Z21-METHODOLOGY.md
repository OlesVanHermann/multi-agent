# z21 — Methodologie de creation d'un agent z21

## Principe

Un agent z21 gere un **gros systeme** avec un **seul groupe de 6 agents** qui chargent des **sous-contextes interchangeables**. Le Master route chaque tache vers le bon sous-contexte via send.sh. Chaque agent charge le contexte (archi.md + memory.md + methodology.md) du sous-repertoire indique dans le dispatch.

## Difference avec x45

| | x45 | z21 |
|---|-----|-----|
| Contexte | Fixe par agent | **Variable** — tous chargent le meme sous-contexte |
| Dispatch | Implicite | **Explicite** — Master route via memory.md + send.sh |
| Scaling | Ajouter des agents | Ajouter des **sous-repertoires** |
| Avantage | Specialisation | **Couverture** d'un gros systeme |

---

## Structure fichiers

```
prompts/{ID}-{nom}/
├── agent.type                    → ../agent_z21.type
├── {ID}-1{XX}.md                 → ../AGENT.md (Master)
├── {ID}-1{XX}-system.md          # Master : routeur de contextes
├── {ID}-1{XX}-memory.md          # Index de TOUS les sous-contextes + mapping mots-cles
├── {ID}-1{XX}-methodology.md     # Regles de dispatch (1 a la fois, surveillance tmux)
├── {ID}-{ID}.md                  → ../AGENT.md (Developer)
├── {ID}-{ID}-system.md           # Dev : stack, regles, workflow + completion obligatoire
├── {ID}-5{XX}.md                 → ../AGENT.md (Tester)
├── {ID}-5{XX}-system.md          # Tester : INPUT/OUTPUT, regles, pieges connus, 3 notifications
├── {ID}-7{XX}.md                 → ../AGENT.md (Reviewer)
├── {ID}-7{XX}-system.md          # Reviewer : criteres C1-C6, perimetre, OUTPUT structure
├── {ID}-8{XX}.md                 → ../AGENT.md (Coach)
├── {ID}-8{XX}-system.md          # Coach : workflow, regles append-only, notification fin
├── {ID}-9{XX}.md                 → ../AGENT.md (Architect)
├── {ID}-9{XX}-system.md          # Architect : responsabilites, archi globale, completion
├── {ID}-1{XX}.model              → ../{model}.model
├── {ID}-1{XX}.login              → ../{login}.login
├── ... (model+login pour chaque satellite)
│
├── {sous-contexte-1}/
│   ├── archi.md                  # Architecture de CE morceau
│   ├── memory.md                 # Etat, bugs, historique (append-only)
│   └── methodology.md            # Comment travailler sur ce morceau
├── {sous-contexte-2}/
│   ├── archi.md
│   ├── memory.md
│   └── methodology.md
└── ...
```

---

## Etapes de creation

### 1. Explorer le systeme cible

Lancer des agents Explore en parallele pour scanner :
- **Code backend** : tous les fichiers, endpoints, schema PG, tests
- **Bilans/history** : bugs detectes, decisions, patterns etablis
- **Infra** : ports, config, systemd, storage layers

### 2. Decouper en sous-contextes

Regrouper par **domaine fonctionnel** (pas par fichier). Exemples :
- Drive : `b-crud`, `b-sharing-links`, `b-thumbnail-gen`, `f-file-browser`
- Mail : `b-imap-connect`, `b-send`, `b-folders`, `f-mail-compose`
- Chat : `streaming_sse`, `sessions_crud`, `frontend_hooks`

**Convention de nommage** (depuis 370/371 v2) :
- `b-*` : backend contexts
- `f-*` : frontend contexts

### 3. Creer le repertoire

```bash
mkdir -p prompts/{ID}-{nom}/{ctx1,ctx2,...}
```

### 4. Creer les 6 agents satellites

Chaque satellite a un `-system.md`. **Elements obligatoires par role** :

#### Master (1XX)
- **system.md** : identite, liste agents, index → memory.md
- **memory.md** : index COMPLET (tableau ID/scope/fichiers/port), mapping mots-cles, bugs connus, etat par contexte
- **methodology.md** : cycle (recevoir→analyser→router→dispatcher→attendre→enchainer), INTERDIT (jamais lire le code), format de dispatch (CONTEXT/TASK/ERROR/FILES_HINT), surveillance tmux

#### Developer (3XX)
- **Principe** : recoit du Master, charge le contexte, execute, **signale completion OBLIGATOIRE** au Master via Redis
- **Stack technique** : liste complete (backend, frontend, storage, tests)
- **Regles ABSOLUES** : specifiques au domaine (ex: IMAP SEND pas SMTP, SSE no-buffering)
- **Repertoire de dev** : chemins exacts de tous les fichiers source

#### Tester (5XX)
- **INPUT/OUTPUT** : quoi tester, ou mettre les tests
- **Fichiers source a tester** : liste avec chemins absolus
- **Regles** : framework (pytest-asyncio, httpx), mocking (dependency_overrides), anti-regression
- **Pieges connus** : liste numerotee des bugs de test recurrents
- **Pattern de test** : fixture type a copier
- **Commande test** : exacte (`python3` pas `python`)
- **Notification 3 destinations** : Master + Dev + Master 100 — JAMAIS terminer sans

#### Reviewer (7XX)
- **Criteres C1-C6** : fonctionnel + patterns + regression + auth + code mort
- **INPUT/OUTPUT** : format attendu + rapport structure
- **Perimetre fichiers** : liste exacte
- **Completion obligatoire** : Redis XADD au Master

#### Coach (8XX)
- **Principe** : recoit rapport, met a jour memory.md + methodology.md
- **Workflow** : 4 etapes (lire→update memory→eval methodology→notifier)
- **Regles** : dater, append-only, < 200 lignes, modifier methodology si pattern 3x

#### Architect (9XX)
- **Responsabilites** : creer contextes, update archi.md, coherence, deduplication
- **Architecture globale** : resume du systeme (ports, storage, schema)
- **Completion obligatoire** : send.sh ou Redis au Master

### 5. Creer les sous-contextes

Pour chaque sous-repertoire, creer 3 fichiers :

#### archi.md
- Titre `# {nom} — Architecture {description}`
- **Scope** : 1-2 phrases
- **Fichiers** : tableau avec nom + role
- **Endpoints** : si applicable
- **Schema PG** : si applicable
- **Pattern technique** : comment ca marche

#### memory.md
- Etat initial : `## Etat : initial`
- Historique vide
- Append-only par le Coach apres chaque cycle

#### methodology.md
- **Avant de coder** : 3-4 etapes (lire le code, verifier schema, etc.)
- **Points d'attention** : pieges specifiques au domaine
- **Tests** : commande exacte

### 6. Poser les symlinks

```bash
cd prompts/{ID}-{nom}

# Type
ln -sf ../agent_z21.type agent.type

# Entry points (AGENT.md)
for id in {ID}-1{XX} {ID}-{ID} {ID}-5{XX} {ID}-7{XX} {ID}-8{XX} {ID}-9{XX}; do
  ln -s ../AGENT.md ${id}.md
done

# Model + Login
ln -s ../opus-4-6.model {ID}-1{XX}.model    # Master = opus
ln -s ../opus-4-6.model {ID}-{ID}.model     # Dev = opus
ln -s ../sonnet-4-6.model {ID}-5{XX}.model  # Tester = sonnet
ln -s ../sonnet-4-6.model {ID}-7{XX}.model  # Reviewer = sonnet
ln -s ../sonnet-4-6.model {ID}-8{XX}.model  # Coach = sonnet
ln -s ../sonnet-4-6.model {ID}-9{XX}.model  # Architect = sonnet

ln -s ../claude1a.login {ID}-1{XX}.login
ln -s ../claude1a.login {ID}-{ID}.login
ln -s ../claude1a.login {ID}-5{XX}.login
ln -s ../claude1b.login {ID}-7{XX}.login
ln -s ../claude1b.login {ID}-8{XX}.login
ln -s ../claude1b.login {ID}-9{XX}.login
```

### 7. Verifier

```bash
# API contextes
curl -s http://localhost:8050/api/agent/{ID}/contexts | python3 -m json.tool

# Symlinks valides
find prompts/{ID}-{nom}/ -type l -exec test ! -e {} \; -print
```

---

## Checklist creation z21

- [ ] Explorer le systeme (code + bilans + infra)
- [ ] Decouper en sous-contextes (b-* backend, f-* frontend)
- [ ] Creer le repertoire + sous-repertoires
- [ ] Ecrire les 6 system.md (avec completion obligatoire)
- [ ] Ecrire memory.md du Master (index + mapping mots-cles + bugs connus)
- [ ] Ecrire methodology.md du Master (dispatch + INTERDIT + surveillance tmux)
- [ ] Ecrire archi.md + memory.md + methodology.md par sous-contexte
- [ ] Poser les symlinks (agent.type, AGENT.md, model, login)
- [ ] Verifier API contextes
- [ ] Tester le bouton CTX dans le dashboard

---

## Evolution entre versions

### v1 (370 initial)
- system.md basique : identite + role
- Pas de workflow de dispatch
- Pas de completion obligatoire
- Sous-contextes a granularite large (9 contextes)

### v2 (370/371 ameliore)
- **Master** : methodology avec INTERDIT, format dispatch, surveillance tmux
- **Dev** : Principe (recoit/charge/execute), completion Redis OBLIGATOIRE
- **Tester** : INPUT/OUTPUT, pieges connus, pattern fixture, 3 notifications
- **Reviewer** : criteres C1-C6, perimetre fichiers, rapport structure
- **Coach** : workflow 4 etapes, notification fin
- **Architect** : completion obligatoire
- Sous-contextes fins : `b-*` (backend) + `f-*` (frontend), 60-88 contextes
- Bugs connus documentes dans memory.md du Master
