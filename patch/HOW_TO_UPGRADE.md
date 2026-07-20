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
                          # synchronisés. Depuis v3.2.X, une migration
                          # sémantique idempotente ajoute aussi le contrat
                          # résultat-first aux system.md existants, avec backup.
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

### Dashboard systemd durci (v3.1.4+)

`upgrade.sh` met à jour le framework, mais ne modifie jamais les unités locales
dans `/etc/systemd/system`. Après une mise à jour, comparer le drop-in du
dashboard avec `setup/multiagent-dashboard-hardening.conf.example`, puis lancer :

```bash
./scripts/check-dashboard-systemd.sh
sudo systemctl daemon-reload
sudo systemctl restart multiagent-dashboard.service
```

Le service ne charge pas le shell interactif ni NVM. Exposer les binaires dans
un répertoire stable présent dans le `PATH` du drop-in (ne pas inscrire une
version NVM en dur dans l'unité) :

```bash
mkdir -p ~/.local/bin
# NE PAS lier un binaire sur lui-même : si `command -v` résout déjà dans
# ~/.local/bin (installeurs claude/codex), ln -sfn REMPLACERAIT le binaire
# par un lien auto-référent cassé.
for b in node claude codex; do
  src=$(command -v "$b") || continue
  [ "$src" = "$HOME/.local/bin/$b" ] || ln -sfn "$src" ~/.local/bin/"$b"
done
```

Le backend doit pouvoir écrire dans `logs/`, `uploads/`, `crontab/`,
`keepalive/` et `prompts/`. Ce dernier contient notamment les sélections
`*.model`, `*.login` et `*.effort` du panneau web.

Le panneau nomme clairement `Défaut global`. Il ne présente pas de popup
supplémentaire : sélectionner cette ligne constitue la confirmation explicite ;
le backend continue d'exiger `confirm_global=true` pour tout autre client.
Pour empêcher l'architecte d'hériter d'une future bascule globale, créer
manuellement un override projet (adapter le modèle Claude choisi) :

```bash
ln -sfn claude-opus-4-8.model prompts/000.model
```

Les fichiers `prompts/*.model` sont des données projet préservées : cette
opération reste volontairement manuelle et hors du périmètre d'`upgrade.sh`.

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

Pour installer explicitement la ligne 3.1 :

```bash
./patch/upgrade.sh v3.1.1
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
   - migration résultat-first et livraison pilotée par les preuves des prompts agents existants avec
     `patch/rebalance-agent-prompts.py` : contenus locaux conservés, originaux
     sous `removed/rebalance-prompts/`, rapport dans l'upgrade backup.
7. Installe les dépendances Python.

Depuis v3.1.17, les sessions tmux et les clés Redis n'utilisent plus
`MA_PREFIX` : `agent-300`, `agent:300:inbox`, `wal`, `completion`. Si Redis est
joignable pendant l'upgrade, `migrate-agent-addresses.sh --apply` déplace les
anciennes clés automatiquement. Sinon, elles seront recréées sous leur nom
canonique au redémarrage ; le migrateur reste exécutable manuellement avant ce
redémarrage.

### Migration des prompts v3.2.X

Voir la référence normative
[HOW TO WRITE AND REWRITE PROMPTS](<../docs/HOW TO WRITE AND REWRITE PROMPTS.md>).

Le dry-run compte les prompts concernés sans les modifier. La passe réelle
ajoute la finalité résultat-first et le contrat de décision par hard gates aux
prompts projet, notamment aux créateurs 150/160/170. Les anciens rôles
1XX/3XX/5XX/7XX/8XX/9XX reçoivent leur contrat spécialisé ; les futurs
mono/x45/z21 héritent de la même écriture.

Contrôle après upgrade :

```bash
python3 patch/rebalance-agent-prompts.py --check
```

Le résultat normal est `updated=0`. Opt-out d'urgence :

```bash
MA_SKIP_PROMPT_REBALANCE=1 ./patch/upgrade.sh
```

---

## Migration v3.0.x → v3.1.x : Claude Code + Codex CLI

La ligne 3.0.x pilote uniquement Claude Code. La ligne 3.1.x ajoute Codex CLI
interactif avec le forfait ChatGPT, sans remplacer les prompts, mémoires,
historiques ou streams Redis des agents.

### Résumé des changements

| Élément | v3.0.x | v3.1.x |
|---|---|---|
| Moteur | Claude Code | Déduit du modèle : `claude-*` ou `gpt-*` |
| Modèles GPT | absents | `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna` |
| Slot visible | `claude1a`…`claude4b` | `login1a`…`login4b` |
| Profil physique | `login/claude1a` | `login/claude1a` ou `login/codex1a` selon le modèle |
| Instructions projet | `CLAUDE.md` | `CLAUDE.md` et `AGENTS.md → CLAUDE.md` |
| Interface | modèle Claude + profil Claude | un modèle et un slot neutre ; aucun sélecteur de CLI |

Exemple de résolution :

```text
login2b + claude-opus-4-8 → CLAUDE_CONFIG_DIR=login/claude2b
login2b + gpt-5.6-sol     → CODEX_HOME=login/codex2b
```

Le changement de modèle est atomique : sélectionner un modèle `gpt-*` dans le
dashboard sélectionne Codex. Il ne faut créer aucun fichier `.cli`.

### Mise à jour automatique recommandée

Depuis une v3.0.x récente, **une seule exécution** suffit :

```bash
./scripts/infra.sh stop 2>/dev/null || true
./patch/upgrade.sh v3.1.1
```

### Ce que `upgrade.sh` fait automatiquement

Le périmètre de `upgrade.sh` ne change pas. Il effectue notamment :

1. met à jour les répertoires framework `scripts/`, `web/`, `docs/`, `patch/`,
   `setup/`, `tests/`, `templates/`, `examples/`, `framework/` et `.github/` ;
2. installe donc automatiquement le moteur Codex, ses marqueurs TUI, le bridge,
   le backend et les sources du dashboard 3.1.x ;
3. met à jour `CLAUDE.md`, `README.md`, les dépendances et la documentation ;
4. synchronise uniquement les cinq prompts canoniques ;
5. fusionne les règles `permissions.deny` des profils Claude ;
6. conserve volontairement tous les `.model`, `.login`, liens de sélection,
   prompts d’agents, mémoires et credentials du projet.

Il **ne crée donc pas** `AGENTS.md`, les modèles GPT, les slots neutres, les
profils Codex ou les nouveaux liens `.login`. Ces opérations sont manuelles
parce qu’elles appartiennent à la configuration du projet.

### Ce qu’il faut faire manuellement après `upgrade.sh`

Depuis la racine du projet, créer d’abord les fichiers de compatibilité 3.1.x :

```bash
cd /home/ubuntu/multi-agent

# Codex lit AGENTS.md ; une seule source reste maintenue.
ln -sfn CLAUDE.md AGENTS.md

# Catalogue des modèles exposés dans l’interface.
printf 'gpt-5.6-sol\n'   > prompts/gpt-5-6-sol.model
printf 'gpt-5.6-terra\n' > prompts/gpt-5-6-terra.model
printf 'gpt-5.6-luna\n'  > prompts/gpt-5-6-luna.model

# Slots neutres visibles dans le dashboard.
for slot in 1a 1b 2a 2b 3a 3b 4a 4b; do
  printf 'login%s\n' "$slot" > "prompts/login${slot}.login"
done
```

Migrer ensuite les liens explicites existants sans changer le slot choisi :

```bash
while IFS= read -r link; do
  target=$(readlink "$link")
  base=$(basename "$target")
  if [[ "$base" =~ ^claude([1-4][ab])\.login$ ]]; then
    prefix="${target%$base}"
    ln -sfn "${prefix}login${BASH_REMATCH[1]}.login" "$link"
  fi
done < <(find prompts -type l -name '*.login' -print)
```

Si le profil par défaut historique était `claude1a`, le résultat devient :

```bash
ln -sfn login1a.login prompts/default.login
```

Adapter `login1a` si un autre slot était le défaut. Ne pas renommer les
répertoires physiques `login/claude*` : ils restent utilisés par Claude Code.

### Création des profils Codex

Les slots neutres ne contiennent aucun credential. Chaque profil physique
Codex doit être connecté une fois :

```bash
source setup/login_create.sh \
  codex1a codex1b codex2a codex2b \
  codex3a codex3b codex4a codex4b
```

Choisir **Sign in with ChatGPT**, jamais une clé API. Il est possible de ne
créer que les profils réellement utilisés, par exemple :

```bash
source setup/login_create.sh codex1a codex1b
```

Contrôle :

```bash
CODEX_HOME="$PWD/login/codex1a" codex login status
# attendu : Logged in using ChatGPT
```

### Vérifications après upgrade

```bash
grep -m1 'Multi-Agent System' CLAUDE.md
readlink AGENTS.md
readlink prompts/default.login
cat prompts/login1a.login
for f in prompts/gpt-5-6-{sol,terra,luna}.model; do echo "$f: $(cat "$f")"; done
```

Résultat attendu :

```text
# Multi-Agent System v3.1.1
CLAUDE.md
login1a.login
login1a
prompts/gpt-5-6-sol.model: gpt-5.6-sol
prompts/gpt-5-6-terra.model: gpt-5.6-terra
prompts/gpt-5-6-luna.model: gpt-5.6-luna
```

Puis reconstruire/redémarrer les services :

```bash
./scripts/web.sh restart
./scripts/infra.sh start
./scripts/agent.sh start all
```

Dans le panneau Login/Model, choisir par exemple `login1a` et
`gpt-5-6-sol`. Le tmux doit démarrer Codex, saisir `/model gpt-5.6-sol`, puis
charger le même `deviens agent` et les mêmes fichiers mémoire que Claude.

### Réparation manuelle si une ancienne instance reste incohérente

Cette procédure est idempotente et peut être exécutée par Claude ou Codex :

```bash
cd /home/ubuntu/multi-agent

# Catalogue minimal attendu
for slot in 1a 1b 2a 2b 3a 3b 4a 4b; do
  printf 'login%s\n' "$slot" > "prompts/login${slot}.login"
done

printf 'gpt-5.6-sol\n'   > prompts/gpt-5-6-sol.model
printf 'gpt-5.6-terra\n' > prompts/gpt-5-6-terra.model
printf 'gpt-5.6-luna\n'  > prompts/gpt-5-6-luna.model

# Migration de tous les liens explicites claudeXa.login → loginXa.login
while IFS= read -r link; do
  target=$(readlink "$link")
  base=$(basename "$target")
  if [[ "$base" =~ ^claude([1-4][ab])\.login$ ]]; then
    prefix="${target%$base}"
    ln -sfn "${prefix}login${BASH_REMATCH[1]}.login" "$link"
  fi
done < <(find prompts -type l -name '*.login' -print)

ln -sfn CLAUDE.md AGENTS.md
ln -sfn login1a.login prompts/default.login  # seulement si 1a est votre défaut
```

Ne pas renommer les répertoires physiques `login/claude*` et `login/codex*` :
ils stockent des authentifications différentes. Seuls les fichiers/symlinks
de sélection sous `prompts/` utilisent le préfixe neutre `login`.

Si l’interface affiche encore l’erreur « model incompatible with engine
claude », le backend 3.0 tourne encore : redémarrer `web.sh` après l’upgrade et
vérifier que `CLAUDE.md` annonce bien 3.1.1.

---

## Migration v2.X → v3.X : lancer l'upgrade DEUX FOIS

L'upgrade.sh **déjà présent** sur une machine v2 ne connaît pas les
migrations v3 (bench/, deny, prompts canoniques) :

```bash
./patch/upgrade.sh          # passe 1 : installe le nouvel outillage (patch/, scripts/, tests/…)
./patch/upgrade.sh --dry-run   # contrôle : la section Migrations doit apparaître
./patch/upgrade.sh          # passe 2 : applique les migrations v3
python3 -m pytest tests/ -q  # 579+ tests attendus verts
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
| v3.2.X | 2026-07 | Prompts résultat-first 70/20/10, créateurs 150/160/170, migration automatique et récupérable des prompts projet via upgrade.sh |
| v3.2.0 | 2026-07 | Gates x45, anti-spécialisation R4, coût mesuré, banc scellé, méthodologies delta/Pareto, ablation, compétences partagées, topologies variables, observateurs paramétriques NNN-2XX/NNN-8XX |
| v3.0.4–v3.0.7 | 2026-07 | redis.sh mot de passe env-only, `.github/` dans les manifests, scroll tmux (DISABLE_MOUSE dans les profils), défaut opus-4-8, dashboard résilient aux rebuilds frontend, triangle auto-resolve par vivacité (send.sh/done.sh), sessions Keycloak 7 j — les instances existantes appliquent les durées via kcadm (`docs/AUTH.md`) |
| v3.0 | 2026-07 | Boucle verify au bridge (C1), WAL/budgets/stall (C2), banc bench/ (C0), migrations upgrade.sh |
| v3.1.2 | 2026-07 | Agent Architecte `000` visible dans la grille et les mises à jour temps réel, contrôles toujours protégés |
| v3.1.1 | 2026-07 | Slots neutres `login1a…login4b`, migration des liens Claude, modèle comme unique sélecteur |
| v3.1.0 | 2026-07 | Codex CLI interactif, profils ChatGPT, marqueurs TUI multi-moteurs |
| v2.5 | 2026-03 | Effort selector, usage bars, agents 310/311/312, keepalive panel, Keycloak proxy-edge |
| v2.4 | 2026-02 | Format mono/x45/z21, Chrome Bridge extension, agent 150, patch/ dir |
| v2.3 | 2026-02 | Dashboard web React+FastAPI, Keycloak auth, proxy.sh |
| v2.2 | 2026-01 | x45 auto-amélioration, satellites, crontab-scheduler |
| v2.1 | 2026-01 | Bridge Redis Streams, healthcheck, tmux batching |
| v2.0 | 2026-01 | Version initiale |

---

*Issues: https://github.com/OlesVanHermann/multi-agent/issues*
