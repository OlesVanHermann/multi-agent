# Patch Pipeline — Index

Ce répertoire documente le pipeline de patching entre les machines de développement (Mac) et le serveur central (hub).

## Architecture en un coup d'œil

```
Mac                              hub                          GitHub
─────────────────                ──────────────────────       ──────────────
~/multi-agent/       push        bare repo                    origin/main
~/multi-agent-git/ ──────────►  /home/ubuntu/multi-agent.git
                   patch/proj/   ↓ post-receive hook
                   fix-xxx       /home/ubuntu/multi-agent/
                                  cherry-pick sélectif
                                  git push origin main ────►  main + tags
```

## Fichiers

| Fichier | Contenu |
|---------|---------|
| [PIPELINE.md](PIPELINE.md) | Pipeline complet : étapes, commandes, règles, troubleshooting |
| [SETUP-CLIENT.md](SETUP-CLIENT.md) | Setup initial d'une machine Mac/client |
| [SETUP-HUB.md](SETUP-HUB.md) | Setup initial du serveur hub (bare repo + working repo) |

## Commandes rapides

### Mac — pousser un patch

```bash
# Générer les checksums
cd ~/multi-agent
git ls-files core docs scripts web | xargs md5 > file.md5

# Sync + push
./patch/sync-to-git.sh "fix-description"
# Résultat : cd ~/multi-agent-git && git push hub patch/project/fix-description
```

### hub — recevoir et intégrer

```bash
cd /home/ubuntu/multi-agent

# Voir les patches en attente
./patch/hub-receive.sh

# Inspecter avant d'intégrer
git diff --stat main..hub/patch/project/fix-description

# Cherry-pick
./patch/hub-cherry-pick.sh hub/patch/project/fix-description

# Release
./patch/hub-release.sh
```

## Règle fondamentale

**Ne jamais pousser directement sur `main`.** Toujours via une branche `patch/projet/description`.
