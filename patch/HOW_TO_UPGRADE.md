# Guide de Mise à Jour

Ce guide explique comment mettre à jour votre déploiement multi-agent vers une nouvelle version.

---

## Guides par version

Le script de mise à jour est dans `patch/upgrade.sh`. Il préserve automatiquement les fichiers projet et met à jour uniquement le framework.

---

## Structure des fichiers

### Fichiers FRAMEWORK (mis à jour automatiquement)

Ces fichiers viennent du repo officiel et ne doivent **pas** être modifiés localement :

```
scripts/agent-bridge/     # Bridge Python du framework

scripts/                  # Scripts d'orchestration
├── *.sh
└── *.py

patch/                    # Scripts de patch/upgrade
├── upgrade.sh
├── hub-release.sh
└── ...

docs/                     # Documentation framework
requirements.txt          # Dépendances Python
UPGRADE.md               # Ce fichier
```

### Fichiers PROJET (à conserver lors des mises à jour)

Ces fichiers sont spécifiques à votre projet :

```
prompts/                  # Vos prompts personnalisés (répertoires d'agents,
                          # *.model, *.login) — SEULS les 5 .md canoniques
                          # (RULES, CONVENTIONS, PATHS, AGENT, CHROME) sont
                          # synchronisés, avec backup dans removed/
pool-requests/           # Données runtime
├── knowledge/           # Vos inventaires
project/                 # Votre code source
project-config.md        # Votre configuration
login/                   # Credentials des profils Claude — jamais synchronisé
                          # (seules les règles permissions.deny sont fusionnées)
bench/results/           # Résultats de banc locaux — jamais touchés
bench/heldout.txt        # Split held-out du site — préservé s'il existe
logs/                    # Logs (peuvent être supprimés)
sessions/                # Sessions (peuvent être supprimés)
```

`bench/` est un cas hybride : le squelette (run.sh, collect.py, oracles des
tâches synthétiques…) est mis à jour en **fusion, jamais de suppression** —
les tâches importées depuis votre historique et vos résultats survivent.

---

## Processus de mise à jour

### Étape 1: Identifier votre version actuelle

```bash
git describe --tags 2>/dev/null || git log --oneline -1
```

### Étape 2: Sauvegarder vos fichiers projet

```bash
BACKUP_DIR="../multi-agent-backup-$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR
cp -r prompts/ $BACKUP_DIR/
cp -r pool-requests/knowledge/ $BACKUP_DIR/
cp project-config.md $BACKUP_DIR/ 2>/dev/null || true
echo "Backup: $BACKUP_DIR"
```

### Étape 3: Arrêter les agents

```bash
./scripts/infra.sh stop 2>/dev/null || true
tmux kill-server 2>/dev/null || true
```

### Étape 4: Lancer le script de mise à jour

```bash
# Simuler d'abord (aucune modification)
./patch/upgrade.sh --dry-run

# Appliquer la mise à jour
./patch/upgrade.sh
```

### Étape 6: Installer les dépendances

```bash
pip install -r requirements.txt
```

### Étape 7: Vérifier et redémarrer

```bash
python3 scripts/agent-bridge/healthcheck.py
./scripts/agent.sh start all
```

---

## Ce que fait upgrade.sh

1. Clone la release depuis GitHub (surchargeable : `MA_UPGRADE_REPO_URL=file:///miroir`).
2. Vérifie l'intégrité (manifest de checksums + signature GPG du tag, voir C3).
3. Affiche le plan (répertoires, fichiers, migrations) — `--dry-run` s'arrête là.
4. Archive l'état courant dans `removed/<horodatage>_upgrade_backup/`.
5. Synchronise les répertoires framework (`rsync --delete`), en préservant
   `setup/secrets.cfg`.
6. **Migrations idempotentes** (v2→v3 comme v3.X→v3.X+1) :
   - `bench/` en fusion (jamais de suppression ; `results/` et `heldout.txt`
     locaux préservés) ;
   - synchronisation des 5 `.md` canoniques de `prompts/` (backup préalable ;
     les liens symboliques locaux ne sont pas touchés) ;
   - fusion des règles `permissions.deny` (protection oracle V3) dans les
     `login/claude*/settings.json` existants via `patch/merge-deny-rules.py`
     — union des règles uniquement, le reste du fichier ne bouge pas.
7. Installe les dépendances Python.

---

## Migration v2.X → v3.X : lancer l'upgrade DEUX FOIS

L'upgrade.sh **déjà présent** sur une machine v2 ne connaît pas les
migrations v3 (bench/, deny, prompts canoniques) :

```bash
./patch/upgrade.sh          # passe 1 : installe le nouvel outillage (patch/, scripts/, tests/…)
./patch/upgrade.sh --dry-run   # contrôle : la section Migrations doit apparaître
./patch/upgrade.sh          # passe 2 : applique les migrations v3
python -m pytest tests/ -q  # 559+ tests attendus verts
```

Les migrations étant idempotentes, relancer une passe de trop est sans effet.

**Note descendante** : cet upgrade.sh (≥ v3.0.1) refuse les releases plus
anciennes que sa liste de manifest (écart « fichiers hors manifest ») —
c'est l'abandon sûr attendu, rien n'est modifié.

---

## Intégrité du framework (C3)

Les agents tournent en bypass-permissions : une mise à jour altérée
propagerait du code injecté. Deux protections dans `upgrade.sh` :

1. **Manifest de checksums** — `patch/checksums.sha256` est généré par
   `hub-release.sh` à chaque release (sha256 de tous les fichiers framework
   trackés git). `upgrade.sh` recalcule les checksums du framework téléchargé
   et **abandonne** en cas d'écart ou de fichier hors manifest.
2. **Signature GPG du tag** — si `user.signingkey` est configurée sur le hub,
   `hub-release.sh` signe le tag (`git tag -s`). `upgrade.sh` tente
   `git verify-tag` quand la cible est un tag.

Mode strict (recommandé en production) :

```bash
MA_UPGRADE_STRICT=1 ./patch/upgrade.sh v2.13.0
```

En strict, le manifest **et** la signature de tag sont obligatoires (la clé
publique de release doit être importée : `gpg --import release-key.asc`).
Par défaut (non strict), le manifest est vérifié s'il est présent (échec =
abandon) et l'absence de signature ne produit qu'un avertissement.

Avant le remplacement des répertoires framework, l'état courant est archivé
dans `removed/<horodatage>_upgrade_backup/` — aucune suppression définitive.

---

## Mise à jour de Keycloak (cadence)

L'image Keycloak est **épinglée par tag complet + digest** (C2) dans trois
fichiers qui doivent rester identiques :

- `scripts/infra.sh` (variable `KEYCLOAK_IMAGE`)
- `web/docker-compose.yml` (clé `image:`)
- `setup/install_keycloak.sh` (variable `KEYCLOAK_IMAGE`)

Cadence recommandée :

1. **Mensuel** : vérifier les annonces de sécurité Keycloak
   (https://www.keycloak.org/security) et les nouveaux tags sur
   https://quay.io/repository/keycloak/keycloak?tab=tags.
2. **Patch de la même ligne majeure** (ex. 23.0.x → 23.0.y) : mettre à jour
   le tag + digest dans les trois fichiers, puis `docker rm -f ma-keycloak`
   suivi de `./scripts/infra.sh start` ; vérifier `GET /health/ready` et un
   login sur le dashboard.
3. **Montée majeure** (ex. 23 → 26) : traiter comme une migration dédiée —
   les variables d'admin et le mode de démarrage changent entre lignes
   majeures ; tester l'import du realm sur une machine de test d'abord.

Pour récupérer le digest d'un tag :

```bash
docker pull quay.io/keycloak/keycloak:<TAG>
docker inspect quay.io/keycloak/keycloak:<TAG> --format '{{index .RepoDigests 0}}'
```

---

## Historique des versions

| Version | Date | Changements majeurs |
|---------|------|---------------------|
| v3.0 | 2026-07 | Boucle verify au bridge (C1), WAL/budgets/stall (C2), banc bench/ (C0), migrations upgrade.sh |
| v2.5 | 2026-03 | Effort selector, usage bars, agents 310/311/312, keepalive panel, Keycloak proxy-edge |
| v2.4 | 2026-02 | Format mono/x45/z21, Chrome Bridge extension, agent 150, patch/ dir |
| v2.3 | 2026-02 | Dashboard web React+FastAPI, Keycloak auth, proxy.sh |
| v2.2 | 2026-01 | x45 auto-amélioration, satellites, crontab-scheduler |
| v2.1 | 2026-01 | Bridge Redis Streams, healthcheck, tmux batching |
| v2.0 | 2026-01 | Version initiale |

---

*Issues: https://github.com/OlesVanHermann/multi-agent/issues*
