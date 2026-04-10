# 012-012 Methodology — Routing z21

## Routing d'une tâche

1. Lire la tâche reçue
2. Identifier les mots-clés
3. Consulter le tableau "Mapping mots-clés" dans `memory.md`
4. Lire `{sous-contexte}/archi.md` pour confirmer le périmètre
5. Dispatcher le Dev avec : contexte + fichiers cibles

## Cycle dev/test/review

```
1. Dev  → CONTEXT:{ctx} TASK:{desc}      → attendre DONE
2. Test → TEST CONTEXT:{ctx}             → attendre OK/FAIL
3. Review → REVIEW CONTEXT:{ctx}         → attendre OK/BLOCANTS
4. Si BLOCANTS → retour Dev (step 1)
5. Si OK → notifier 100
```

## Dispatch parallèle
Si le Tester et le Reviewer travaillent sur des blocants **indépendants** :
dispatcher Dev + Tester en parallèle pour gagner du temps.

## Mise à jour de l'état
Après chaque tâche terminée, mettre à jour `memory.md` :
- État du sous-contexte : `initial` → `stable`
- Bugs connus si découverts
