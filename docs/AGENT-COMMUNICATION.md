# Communication déterministe entre agents

Le texte décrit le travail ; l'enveloppe identifie la transaction. Un agent ne
reconstruit jamais `FROM`, `TASK_ID`, `CYCLE` ou `CORRELATION_ID` depuis une
phrase. Les seuls points d'entrée autorisés sont :

```bash
# Événement non terminal
TASK_ID="$TASK_ID" CYCLE="$CYCLE" CORRELATION_ID="$CORRELATION_ID" \
REQUESTER_ID="$REQUESTER_ID" OWNER_ID="$OWNER_ID" \
MESSAGE_EVENT=STATUS $BASE/scripts/send.sh 300 "progression factuelle"

# Dispatch avec attente explicite
TASK_ID="$TASK_ID" CYCLE="$CYCLE" CORRELATION_ID="$CORRELATION_ID" \
REQUESTER_ID="$REQUESTER_ID" OWNER_ID=300 \
MESSAGE_EVENT=DISPATCH EXPECTED_EVENT=ARTIFACT_READY \
$BASE/scripts/send.sh 300 "implémenter la spécification liée"

# Terminal
TASK_ID="$TASK_ID" CYCLE="$CYCLE" CORRELATION_ID="$CORRELATION_ID" \
REQUESTER_ID="$REQUESTER_ID" OWNER_ID="$OWNER_ID" \
$BASE/scripts/done.sh 100 ARTIFACT_READY \
"ARTIFACT:pool-requests/done/task.md HASH:<sha256> TESTS:OK"
```

`FROM:` dans le texte et les appels directs à `redis-cli`, `XADD` ou `RPUSH`
sont interdits dans les prompts.

## États de transport

| État | Sens | Effet autorisé |
|---|---|---|
| `DELIVERED` | message persisté et session cible présente | ouvrir l'attente prévue |
| `ORPHANED` | message persisté, session cible absente | ne pas attendre ; dégrader ou relancer explicitement |
| `INVALID` | enveloppe ou événement invalide | corriger ou émettre `PROTOCOL_ERROR` |
| `DUPLICATE` | terminal déjà enregistré | aucune transition supplémentaire |

Un état de transport n'est jamais une preuve de réussite métier.

## Transaction et terminaux

Une transaction conserve `TASK_ID`, `CYCLE`, `CORRELATION_ID`,
`REQUESTER_ID`, `OWNER_ID`, puis `TARGET` et `EXPECTED_EVENT` pour chaque
dispatch. Le Master maintient une seule attente active par corrélation. Les
événements d'un autre cycle, d'une autre corrélation, tardifs ou dupliqués
restent auditables mais ne changent pas l'état courant. L'état durable vit sous
`pool-requests/state/`, jamais uniquement dans le contexte du modèle.

Un agent émet exactement un terminal avec `done.sh` par événement attendu. Il
ne répond jamais à un terminal par un terminal d'acquittement. Un score est une
information qualitative, pas un verdict : la livraison dépend des hard gates,
des critères d'acceptation et de preuves durables archivées avec chemin, hash et
tests.

## Relecture d'un prompt

- commande locale : relire puis répondre brièvement dans le TUI, sans Redis,
  Git, tmux, pool-request ni reprise métier ;
- requête inter-agent corrélée : relire puis émettre uniquement
  `PROMPT_RELOADED` avec la même enveloppe.

Une relecture ne déclenche jamais automatiquement le workflow de démarrage.

