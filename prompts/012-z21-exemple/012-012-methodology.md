# 012-012 Methodology — Routing z21

## Routing d'une tâche

1. Lire la tâche reçue
2. Identifier les mots-clés
3. Consulter le tableau "Mapping mots-clés" dans `memory.md`
4. Lire `{sous-contexte}/archi.md` pour confirmer le périmètre
5. Dispatcher le Dev avec : contexte + fichiers cibles

## Cycle dev/test/review

Après chaque dispatch unique, rendre immédiatement la main. Le bridge reprend
le cycle sur DONE/SCORE/BLOCKED. Aucun sleep, polling Redis/tmux, contrôle de
session, timeout de complétion, redispatch préventif, arrêt ou redémarrage d'un
autre agent.

```
1. Dev  → CONTEXT:{ctx} TASK:{desc}      → rendre la main, reprise sur DONE
2. Test → TEST CONTEXT:{ctx}             → rendre la main, reprise sur OK/FAIL
3. Review → REVIEW CONTEXT:{ctx}         → rendre la main, reprise sur OK/BLOCANTS
4. Si BLOCANTS → retour Dev (step 1)
5. Si OK → notifier 100
```

## Séquencement

Ne jamais dispatcher deux étapes du même cycle en parallèle. Le Tester reçoit
le livrable terminé du Dev ; le Reviewer reçoit ensuite le résultat des tests.

## Mise à jour de l'état
Après chaque tâche terminée, mettre à jour `memory.md` :
- État du sous-contexte : `initial` → `stable`
- Bugs connus si découverts
