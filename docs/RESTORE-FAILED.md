# restore-failed.sh — Restaurer les pages FAILED

## Problème

Les crawlers marquent les pages en erreur dans `studies/<domain>/300/FAILED/`. Certaines de ces erreurs sont des **faux positifs** causés par la saturation du bridge Chrome (HTTP 500/503) et non par une vraie erreur de la page.

Format d'un fichier FAILED :
```
URL|raison|timestamp
```

Raisons possibles :

| Raison | Cause | Faux positif ? |
|--------|-------|----------------|
| `empty_response` | Bridge saturé ou page vide | **Souvent oui** |
| `404_not_found` | Page n'existe pas | Non |
| `403_forbidden` | Accès refusé | Non |
| `500_server_error` | Erreur serveur du site | Non |
| `502_bad_gateway` | Proxy du site en erreur | Non |
| `503_unavailable` | Site indisponible | Parfois |
| `skipped_binary` | URL pointe vers PDF/ZIP/etc. | Non |
| `redirect_external` | Redirige hors domaine | Non |
| `download_error` | Erreur générique | Parfois |

## Usage

```bash
# Dry-run : voir ce qui serait restauré (empty_response par défaut)
./scripts/restore-failed.sh

# Appliquer la restauration
./scripts/restore-failed.sh --apply

# Filtrer par raison
./scripts/restore-failed.sh --reason=empty_response --apply
./scripts/restore-failed.sh --reason=503_unavailable --apply

# Restaurer TOUS les FAILED (toutes raisons)
./scripts/restore-failed.sh --reason=all --apply
```

## Ce que fait le script

Pour chaque fichier FAILED correspondant au filtre :

1. Recrée un **placeholder HTML vide** (`touch html/<sha>.html`, taille 0)
2. Vérifie que l'entrée `INDEX/<sha>` existe (la recrée si besoin)
3. Déplace le fichier FAILED vers `$BASE/removed/`

Au prochain lancement de `crawl*.py`, les placeholders vides seront détectés comme "à télécharger" et retentés.

## Exemples

```bash
# Voir les faux positifs bridge sur tous les domaines
$ ./scripts/restore-failed.sh
=== restore-failed.sh ===
  Studies:  /Users/claude/multi-agent/studies
  Reason:   empty_response
  Mode:     DRY-RUN

  afnic.fr: 11 to restore
  aruba.it: 5 to restore
  hostinger.com: 2 to restore

FOUND: 18 pages to restore
  Run with --apply to restore them

# Restaurer
$ ./scripts/restore-failed.sh --apply
  afnic.fr: 11/11 restored
  aruba.it: 5/5 restored
  hostinger.com: 2/2 restored

DONE: 18/18 pages restored
```

## Prévention

Depuis le patch du 2026-02-15, les erreurs bridge ne créent plus de FAILED :

- **Node.js** (`cdp-bridge-host.js`) : throttle à 8 commandes max, queue de 64, retourne 503 si plein
- **Python** (`chrome-bridge.py`) : retry 3x avec backoff (1s, 2s) sur HTTP 500/502/503
- **Crawlers** (`crawl*.py`) : erreur bridge = SKIP (laisse le placeholder), pas FAILED

Le script `restore-failed.sh` sert à nettoyer les FAILED historiques créés avant ce patch.
