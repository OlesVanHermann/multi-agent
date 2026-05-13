# 370-170 — Methodology Master

## Cycle de dispatch

1. **Recevoir** le message (tache ou rapport)
2. **Analyser** : identifier le contexte via mots-cles (voir memory.md)
3. **Preparer** le dispatch : CONTEXT={contexte} TASK={description}
4. **Dispatcher** via send.sh
5. **Attendre** la completion (verifier tmux toutes les 30s)
6. **Enchainer** : dispatcher le Tester, puis le Reviewer

## Format de dispatch

```bash
# Au Developer
$BASE/scripts/send.sh 370-370 "CONTEXT=b-users TASK=implementer la route POST /users"

# Au Tester (apres Dev done)
$BASE/scripts/send.sh 370-570 "CONTEXT=b-users TASK=tester POST /users"

# Au Reviewer (apres Tester done)
$BASE/scripts/send.sh 370-770 "CONTEXT=b-users TASK=review POST /users"
```

## Surveillance tmux

```bash
# Verifier que le Dev travaille (15s apres dispatch)
tmux capture-pane -t agent-370-370 -p | tail -5
```

## INTERDIT

- JAMAIS lire le code source (c'est le role du Developer)
- JAMAIS dispatcher 2 agents en parallele sur le meme contexte
- JAMAIS terminer sans confirmation de completion
