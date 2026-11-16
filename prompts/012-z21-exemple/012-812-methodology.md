# 012-812 Methodology — Reviewer

## Revue rapide (< 5 min)
1. `git diff HEAD~1 HEAD` — voir les changements
2. Appliquer la checklist de `system.md`
3. Si tous les critères OK → approbation immédiate
4. Si blocant(s) → liste précise avec localisation (fichier:ligne)

## Distinction blocant vs non-blocant
- **Blocant** : régression, sécurité, tests absents → renvoyer au Dev
- **Non-blocant** : style, optimisation → mentionner mais approuver
