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

Le slot d'un terminal est **indépendant du tour** (A9) : il est identifié par
(émetteur, cible, événement, tâche, cycle, corrélation). Un retry depuis un
autre tour — y compris après la fin du tour vue par le bridge — rend donc
`ALREADY_DELIVERED` sans réécrire, et un contenu différent rend
`NOT_DELIVERED` ; changer de `TURN` ne rouvre jamais un slot.
| `ORPHANED` | message persisté, session cible absente | attendre le rejeu au redémarrage, sans réémission en boucle |
| `PARKED_NO_WAKE` | terminal reçu par un membre non coordinateur | il sera lu à son prochain vrai tour, pas immédiatement |
| `INVALID` | enveloppe sans contenu ou malformée | corriger ou utiliser le canal de secours |
| `rescue:` | signal de métadonnée manquante seulement | réparer l'enveloppe avant le résultat métier |

Un état de transport n'est jamais une preuve de réussite métier.

## Aucun message parqué sans lecteur

Un stream qui a un écrivain a un lecteur. Les canaux sans réveil —
`agent:<id>:reports`, `:control`, `:terminals`, `:supervision` — sont drainés
de façon bornée et annexés au **prochain vrai tour** de leur destinataire,
quel que soit son rôle : un worker voit la question qui lui a été posée, un
Master à identifiant nu voit le `TERMINAL_PENDING` que le watchdog lui écrit.
Le non-réveil reste la règle ; il ne justifie jamais qu'un contenu ne soit
jamais lu. Un contrôle ou un terminal ainsi lu n'ouvre aucune obligation et
ne reçoit jamais de réponse terminale.

### Annexation avec échéance (A8)

Le « prochain vrai tour » n'est pas garanti : un Master idle pouvait garder
des heures de rapports « stored; not injected » (constat du 19/08, triangle
334). Le bridge ouvre donc lui-même **un tour de synthèse borné** quand
l'agent est resté idle `ANNEX_FLUSH_IDLE_S` (défaut 120 s) avec du contenu
parqué, au plus une fois par `ANNEX_FLUSH_MIN_INTERVAL_S` (défaut 300 s).
Ce tour présente tout le backlog en une injection (dédupliqué : un rapport
et sa copie wake comptent une fois), n'ouvre aucune obligation — ni terminal
corrélé ni `MASTER_REPORT` — et l'anti-bruit est préservé par le groupage,
pas par le silence.

### Accusés de lecture

`DELIVERED` décrit une écriture Redis, jamais une consommation. Quand un
tour se termine, le bridge écrit un accusé `ma:bus:v1:read:<event_id>`
(`read_at`, `read_by`, `turn_id`) pour le message qui a ouvert le tour et
pour chaque entrée parquée annexée. Le watchdog surveille l'écart : toute
entrée parquée non annexée ou inbox non consommée au-delà de
`UNREAD_DEADLINE_S` (défaut 900 s) produit une alerte `unread_backlog`
(champ `unread_backlog_s` dans le hash agent pour le dashboard).

Un correctif du bridge ne s'applique qu'au redémarrage du process Python.
Chaque bridge publie l'empreinte de son code chargé (`bridge_code_mtime`) ;
le watchdog signale `STALE_BRIDGE` quand le disque est plus récent, et
`./scripts/agent.sh reload-bridge <id>` recharge UNIQUEMENT le bridge
(fenêtre moteur intacte, messages pending rejoués par le consumer group).
Le reload refuse un agent busy sauf `FORCE_RELOAD=1`.

## Adressage explicite

Depuis un agent de triangle, une cible nue est résolue vers le triangle par
commodité. Deux garanties encadrent ce raccourci :

- une cible préfixée `=` n'est **jamais** réécrite : `send.sh =100` atteint le
  Master global même si le coordinateur local tourne ;
- lorsque rien ne tourne, la résolution n'a lieu que si le membre du triangle
  existe réellement ; sinon la cible globale est conservée, son inbox étant
  rejouée au redémarrage.

`send.sh all` diffuse réellement sur les sessions vivantes, une enveloppe par
agent. En l'absence de destinataire, il échoue franchement au lieu d'écrire
dans un stream que personne ne consomme.

## Routage ouvert entre agents

La taxonomie des événements sert au routage, à la corrélation et à
l'anti-bruit. Elle ne constitue jamais une liste d'autorisation : aucun type
d'événement ne permet d'autoriser ou d'interdire à un agent de parler à un
autre.

Tout message inter-agent qui contient un contenu exploitable est actionnable et
atteint le TUI de sa cible, même si son type est inconnu de la taxonomie. Le
type inconnu reste conservé dans l'enveloppe pour l'audit ; il ne justifie ni
blocage ni quarantaine. La quarantaine est réservée aux enveloppes sans contenu
ou malformées, qui ne peuvent pas être injectées de manière fiable.

`CONCLUSION` est le type canonique émis par le Contradictor. L'ancien type
`ADVISORY_CONCLUSION` reste accepté comme alias terminal : dans les deux cas,
l'avis atteint le TUI du Master et n'ouvre aucune obligation de réponse ou
d'acquittement.

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

Indépendamment de cette livraison, chaque tour de travail réel d'un agent de
triangle `NNN-YZZ`, sauf le coordinateur `NNN-1ZZ`, porte une obligation de
supervision. Avant de redevenir idle, l'agent exécute `report-master.sh`. Le
script calcule le coordinateur, publie un `MASTER_REPORT` court et mémorise un
identifiant de tour distinct de la corrélation métier. Cette règle couvre aussi
un prompt utilisateur saisi directement dans le TUI.

| Origine du tour | Livraison au demandeur | Livraison au coordinateur |
|---|---|---|
| `NNN-1ZZ` | terminal corrélé | `MASTER_REPORT` |
| autre agent | terminal corrélé à cet agent | `MASTER_REPORT` |
| utilisateur direct | réponse dans le TUI | `MASTER_REPORT` |
| aucune enveloppe exploitable | signal de secours si nécessaire | `MASTER_REPORT` |

Le rapport est toujours écrit dans `agent:<master>:reports`. Les statuts
`SUCCESS`, `PARTIAL` et `FAILED` restent silencieux : le Master reçoit leur
synthèse bornée au prochain vrai tour. Pour `BLOCKED` et `INFO_REQUIRED`, la
même publication atomique revendique une identité de décision du tour et écrit
au plus un `DECISION_REQUIRED` dans l'inbox du Master. Si `send.sh` ou
`done.sh` a déjà représenté cette décision, aucun second réveil n'est créé.
Les contrôles vivent dans `agent:<id>:control` et les vrais terminaux dans
`agent:<id>:terminals` ; un réveil dérivé d'un rapport n'est jamais un terminal.

Le rapport de supervision ne clôt aucune transaction métier et ne peut jamais
être transformé en `DONE`, `SCORE` ou preuve de réussite. Le contrôle repose
sur Redis, les états du bridge et les hooks moteur : il ne démarre aucun modèle
supplémentaire et ne consomme donc aucun token de supervision.

Chaque enveloppe `ma.bus.v1` distingue quatre identités : le `source_turn_id`
du producteur, l'`event_id` stable, le `report_id` éventuel et le
`decision_id`. Le texte n'est jamais une identité. Un rejeu strict du même
rapport rend `ALREADY_STORED` sans nouvelle écriture ; un autre payload pour le
même tour rend `CONFLICT` et n'écrit rien. Rapport, éventuel réveil et état du
producteur sont validés puis publiés dans une seule exécution Redis.

L'ordre contractuel reste : livraison métier au demandeur d'abord, rapport au
coordinateur ensuite. Il ne faut jamais ajouter une copie manuelle « pour
réveiller » le Master. Le publisher partage le même `decision_id` entre les
deux canaux et garantit un seul réveil pour ce tour et ce décisionnaire.

Le dispositif possède trois filets complémentaires :

1. le hook Stop Claude refuse une première fin de tour de travail sans
   livraison corrélée due ou sans nouveau `MASTER_REPORT`; sa seconde invocation reste
   inactive afin d'éviter toute boucle ;
2. quand un tour se termine sans événement, le bridge réinjecte une seule
   consigne courte ; un second échec produit `PROTOCOL_ERROR` vers le demandeur,
   jamais `DONE` ou `SCORE` ;
3. si le tour ne se termine pas, le watchdog stocke un contrôle `STALL`, puis
   une escalade `PROTOCOL_ERROR`, sans injection dans un TUI.

À réception de `STALL`, le demandeur peut réagir par une seule relance corrélée
et bornée. Il ne sonde jamais sur minuteur. Toute instruction opérateur vers un
agent passe par `send.sh` ; une saisie directe dans un pane tmux ne possède pas
la vérification de soumission du bridge.
