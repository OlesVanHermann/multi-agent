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
| `ALREADY_DELIVERED` | rejeu strict d'un terminal au contenu identique | aucune transition supplémentaire |
| `NOT_DELIVERED` | même slot terminal, contenu différent | ouvrir un nouveau `CYCLE`/`CORR`, puis réémettre |
| `ORPHANED` | message persisté, session cible absente | attendre le rejeu au redémarrage, sans réémission en boucle |
| `INVALID` | enveloppe ou événement invalide | corriger ou utiliser le canal de secours |
| `rescue:` | signal de métadonnée manquante seulement | réparer l'enveloppe avant le résultat métier |

Un état de transport n'est jamais une preuve de réussite métier.

## Canal de secours

Une enveloppe incomplète ne doit jamais réduire un agent au silence.
`send.sh` accepte uniquement `INFO_REQUIRED`, `PROTOCOL_ERROR` ou
`STATUS_REQUIRED` dans ce cas ; `done.sh` accepte uniquement
`INFO_REQUIRED` ou `PROTOCOL_ERROR`. Le transport attribue alors
`TASK=unattributed`, `CYCLE=unattributed` et une corrélation `rescue-*` si
nécessaire. Cette corrélation signale l'incident de protocole et ne remplace
jamais la corrélation métier manquante.

## Transaction et terminaux

Une transaction conserve `TASK_ID`, `CYCLE`, `CORRELATION_ID`,
`REQUESTER_ID`, `OWNER_ID`, puis `TARGET` et `EXPECTED_EVENT` pour chaque
dispatch. Le Master maintient une seule attente active par corrélation. Les
événements d'un autre cycle, d'une autre corrélation, tardifs ou dupliqués
restent auditables mais ne changent pas l'état courant. L'état durable vit sous
`pool-requests/state/`, jamais uniquement dans le contexte du modèle.

Avant le travail, chaque agent écrit dans
`pool-requests/state/<task>/<cycle>/state.md` l'émetteur, la tâche, le cycle,
la corrélation, l'événement attendu et `STATUS=WORKING`. Il ne passe à
`STATUS=DELIVERED` qu'après lecture d'un état de livraison confirmé. Le Master
réconcilie les attentes à chacun de ses tours et utilise `STATUS_REQUIRED`
quand une cible déclare son travail terminé sans événement retourné.

Le bridge matérialise aussi chaque `DISPATCH` sous
`pool-requests/state/<task>/<cycle>/obligations/<agent>.json`. `done.sh`
archive l'obligation concordante dans `obligations-closed/` après écriture
réussie du terminal dans `completion`. Le watchdog rapproche les fichiers
ouverts du stream structuré, envoie un rappel corrélé après
`OBLIGATION_REMINDER_S` (900 secondes par défaut), puis une seule alerte au
double du délai. Un rappel réclame le terminal dû et ne redispatche jamais le
travail.

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
## Garantie de retour et détection du silence

Une réponse narrative enregistrée dans l'outbox est une transcription, pas une
livraison métier. Tout tour inter-agent corrélé doit donc exécuter `send.sh` ou
`done.sh` avant de redevenir idle.

Le dispositif possède trois filets complémentaires :

1. le hook Stop Claude refuse une première fin de tour corrélée sans événement ;
   il est inactif pour `FROM=cli`, les tours non corrélés et sa propre seconde
   invocation afin d'éviter toute boucle ;
2. quand un tour se termine sans événement, le bridge réinjecte une seule
   consigne courte ; un second échec produit `PROTOCOL_ERROR` vers le demandeur,
   jamais `DONE` ou `SCORE` ;
3. si le tour ne se termine pas, le watchdog publie `STALL` au demandeur et
   relance l'agent une seule fois. Après une nouvelle fenêtre silencieuse, il
   publie `PROTOCOL_ERROR`.

À réception de `STALL`, le demandeur peut réagir par une seule relance corrélée
et bornée. Il ne sonde jamais sur minuteur. Toute instruction opérateur vers un
agent passe par `send.sh` ; une saisie directe dans un pane tmux ne possède pas
la vérification de soumission du bridge.
