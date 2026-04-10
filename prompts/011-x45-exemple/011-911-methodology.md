# 011-911 Methodology — Architect

## Bootstrap
1. `mkdir -p $BASE/project/plan-TODO $BASE/project/plan-DOING $BASE/project/plan-DONE $BASE/pipeline/011-output`
2. Vérifier les symlinks : `find prompts/011-x45-exemple -type l -exec test ! -e {} \; -print`
3. `$BASE/scripts/send.sh 011-111 "go"`

## Escalade (score bloqué > 3 cycles)
1. Lire `011-511-memory.md` — identifier le pattern d'échec récurrent
2. Lire `011-011-methodology.md` + `011-811-memory.md`
3. Reformuler les critères ou la grille d'évaluation si incohérence
4. Ne jamais modifier `system.md` — uniquement `memory.md` et `methodology.md`
