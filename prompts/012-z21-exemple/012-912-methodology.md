# 012-912 Methodology — Architect z21

## Bootstrap
1. Vérifier symlinks : `find prompts/012-z21-exemple -type l -exec test ! -e {} \; -print`
2. Vérifier sous-contextes : `ls prompts/012-z21-exemple/b-*/`
3. `$BASE/scripts/send.sh 012-012 "go"`

## Ajout d'un sous-contexte
1. `mkdir -p prompts/012-z21-exemple/b-{nouveau}/`
2. Créer `archi.md`, `memory.md`, `methodology.md` dans le nouveau répertoire
3. Ajouter le sous-contexte au tableau dans `012-012-memory.md`
4. Ajouter les mots-clés dans le mapping

## Escalation
- Si blocage > 3 cycles : inspecter `archi.md` du contexte bloqué
- Vérifier cohérence entre archi.md et les fichiers réels
- Reformuler le périmètre si nécessaire (ne jamais deviner)
