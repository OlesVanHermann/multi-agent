# Patch — priorité d'exécution des demandes opérateur

## Objectif

Empêcher les agents x45 de transformer une memory périmée, une whitelist
historique ou une métadonnée bridge manquante en refus d'exécuter une demande
explicite de l'opérateur.

## Fichiers framework à pousser sur mx9

- `prompts/AGENT.md`
- `templates/x45/prompts/AGENT.md`
- `examples/3-x45-simple/prompts/AGENT.md`
- `examples/4-x45-complet/prompts/AGENT.md`
- `tests/test_prompt_operator_priority.py`

## Comportement ajouté

1. `system.md` reste le rôle et le processus par défaut, mais n'est plus un
   motif de refus pour une demande utilisateur sûre dans le projet.
2. `memory.md` devient explicitement un contexte non exhaustif et potentiellement
   périmé ; l'état physique et la demande récente priment.
3. `TASK`, `CYCLE` et `CORR` restent obligatoires pour les transitions
   inter-agents ambiguës, jamais pour une commande directe de l'opérateur.
4. `FROM=cli` répond dans le TUI ; aucune tentative de routage vers `cli` avec
   `send.sh`/`done.sh`.
5. Un prérequis secondaire indisponible bloque seulement sa preuve. Le reste est
   exécuté et la preuve est marquée `NOT_RUN`.
6. Les frontières fortes restent inchangées : secrets, autre projet/triangle,
   prompts sans rôle autorisé, action destructive ou infrastructure hôte hors
   mandat.

## Ajustements projet locaux associés

Ces fichiers illustrent les migrations à conserver sur la machine projet mais
ne font pas partie du framework générique à pousser sur mx9 :

- `prompts/380-rewrite-livekit-rust/380-180-system.md`
- `prompts/385-dev-browser/385-185-system.md`
- `prompts/373-backend-greffier-transfer/373-373-system.md`
- `prompts/373-backend-greffier-transfer/373-373-memory.md`

## Validation

```bash
python3 -m pytest tests/test_prompt_operator_priority.py -q
```

Après déploiement sur une machine projet, demander aux agents actifs de relire
leurs prompts. Aucun redémarrage n'est requis pour les agents dont le bridge
injecte la demande de relecture.
