# Configuration des Chemins

## Variables

Tous les prompts utilisent ces variables. Elles sont définies dans `project-config.md` à la racine.

| Variable | Description | Défaut |
|----------|-------------|--------|
| `$BASE` | Racine multi-agent | `/chemin/vers/multi-agent` |
| `$POOL` | Pool requests | `$BASE/pool-requests` |
| `$PROJECT` | Projet cible (code source) | `$BASE/project` |
| `$LOGS` | Logs des agents | `$BASE/logs` |
| `$PROMPTS` | Prompts des agents | `$BASE/prompts` |
| `$REMOVED` | Fichiers supprimés (au lieu de rm) | `$BASE/removed` |

---

## RÈGLE DE SÉCURITÉ

**JAMAIS de suppression. Toujours déplacer vers $REMOVED/**

```bash
# INTERDIT : rm, rm -rf, unlink
# OBLIGATOIRE :
mv "$fichier" "$REMOVED/$(date +%Y%m%d_%H%M%S)_$(basename $fichier)"
```

---

## Chemins dérivés

| Usage | Chemin |
|-------|--------|
| PR pending | `$POOL/pending/` |
| PR assigned | `$POOL/assigned/` |
| PR done | `$POOL/done/` |
| Specs | `$POOL/specs/` |
| Tests manifests | `$POOL/tests/` |
| Knowledge/Inventory | `$POOL/knowledge/` |
| State | `$POOL/state/` |
| Sessions | `$BASE/sessions/` |
| Agent logs | `$LOGS/{agent_id}/` |

---

## Dans les prompts

Remplacer les chemins hardcodés par les variables :

```bash
# AVANT (hardcodé)
cat /Users/claude/projet-new/pool-requests/pending/PR-DOC-*.md

# APRÈS (variable)
cat $POOL/pending/PR-DOC-*.md
```

---

## Initialisation

Au démarrage, l'agent 900 (Architect) :

1. Lit `$BASE/project-config.md`
2. Exporte les variables :
   ```bash
   export BASE="/chemin/vers/multi-agent"
   export POOL="$BASE/pool-requests"
   export PROJECT="$BASE/project"
   export LOGS="$BASE/logs"
   export REMOVED="$BASE/removed"
   ```
3. Les agents héritent de ces variables via leur environnement

---

## Configuration projet

Créer `$BASE/project-config.md` :

```markdown
# Configuration Projet

## Chemins
BASE=/Users/xxx/multi-agent
POOL=$BASE/pool-requests
PROJECT=$BASE/project
LOGS=$BASE/logs
REMOVED=$BASE/removed

## Projet
PROJECT_NAME=mon-projet
PROJECT_REPO=https://github.com/xxx/mon-projet

## Agents Dev (3XX)
AGENTS_DEV=300,301,302
AGENT_300_NAME=backend
AGENT_301_NAME=frontend
AGENT_302_NAME=api

## API Doc (optionnel)
API_DOC_PATH=$PROJECT/docs/api
```

---

*Voir `examples/` pour des exemples concrets.*
