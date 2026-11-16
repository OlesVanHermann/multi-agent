# Audit des communications du triangle 334

Date d'observation : 27 juillet 2026

Version du framework observée : v3.2.11

Périmètre : agents `334`, `334-134`, `334-234`, `334-334`, `334-534`,
`334-734`, `334-834` et `334-934`

## Objet et méthode

Ce document constate la part utile et non utile des échanges entre les agents
dans le but de développer ce que l'utilisateur a demandé.

L'observation repose uniquement sur :

- les sessions et panes tmux actives ;
- les journaux `bridge_20260727_12*.log` ;
- les événements corrélés affichés dans les panes ;
- les preuves de livraison `DELIVERED`, artefacts, tests, scores et hashes
  mentionnés par les agents.

Aucun prompt n'a été lu pendant l'observation. Aucun message, fichier métier,
service, agent ou état Redis n'a été modifié.

Les nombres de caractères proviennent des lignes `Response sent`. Ils mesurent
le volume de texte traité par le bridge, pas un nombre exact de tokens
facturés.

## Synthèse

Le canal de communication fonctionne : les messages, rapports, scores et
terminaux sont corrélés et atteignent leur destinataire avec un état
`DELIVERED`.

La communication reste cependant fortement déséquilibrée. Des échanges utiles
produisent du code, des tests et des preuves, mais ils sont entourés de nombreux
tours consacrés à des relances protocolaires, des événements tardifs ou des
livraisons déjà acquittées.

Sur la session observée après le redémarrage du triangle vers 12:03 :

| Agent | Réponses modèle | Caractères | Entrants | Relances protocole | `PROTOCOL_ERROR` | Messages en queue non traités immédiatement |
|---|---:|---:|---:|---:|---:|---:|
| `334` | 3 | 34 954 | 1 | 0 | 0 | 0 |
| `334-134` | 101 | 1 126 660 | 99 | 20 | 5 | 0 |
| `334-234` | 7 | 91 968 | 5 | 7 | 3 | 9 |
| `334-334` | 6 | 56 596 | 4 | 6 | 2 | 10 |
| `334-534` | 5 | 59 666 | 3 | 2 | 1 | 0 |
| `334-734` | 2 | 17 420 | 0 | 0 | 0 | 0 |
| `334-834` | 6 | 62 727 | 4 | 6 | 4 | 8 |
| `334-934` | 5 | 54 659 | 3 | 0 | 0 | 0 |
| **Total** | **135** | **1 504 650** | **119** | **41** | **15** | **27** |

`334-134` concentre environ 75 % des réponses et du volume textuel. Il est à
la fois le point central de la coordination utile et le principal
amplificateur du trafic protocolaire.

Les 41 relances représentent à elles seules au moins 41 tours sans progrès
métier direct. Ce minimum ne comprend pas les tours supplémentaires déclenchés
par les `PROTOCOL_ERROR`, les rapports hiérarchiques et la reclassification
d'événements tardifs.

## Communications utiles

### Développement et tests

`334-334` produit le travail métier le plus direct :

- développement des contre-preuves du cycle 8 de la tâche 127 ;
- création d'un test de 442 lignes ;
- exécution des tests correspondants ;
- livraison antérieure du terminal `DONE` de la tâche 128/R8.

Ces échanges transforment la demande utilisateur en code et en validation
exécutable.

### Évaluation et preuves

`334-534` a réalisé une évaluation complète de R8 :

- score 97 ;
- bilan durable ;
- SHA-256 vérifié ;
- score et rapport livrés avec `state=DELIVERED`.

Le premier échange contenant ces résultats est utile, car il apporte une
décision fondée sur des preuves.

### Observation de l'état réel

`334` a distingué correctement :

- les artefacts prometteurs ;
- le travail encore en cours chez le Developer ;
- l'absence temporaire de paquet officiellement promu.

Il a transmis un statut non terminal au Master sans fabriquer de verdict
définitif.

### Audit contradictoire

`334-234` a apporté des constats utiles sur :

- l'état réel des tâches 127 et 128 ;
- les preuves présentes et absentes ;
- la différence entre une demande visible dans un TUI et une demande
  persistée ;
- la persistance d'une régression du garde de communication.

La première démonstration de chaque défaut constitue une information utile.

### Arbitrage

`334-934` a produit un arbitrage documenté concernant la régression du garde
après upgrade :

- décision explicite ;
- artefact daté ;
- hash ;
- tests ciblés ;
- livraison au Master.

Cet échange réduit une ambiguïté et fournit une conclusion exploitable.

### Livraison

Les événements utiles suivants ont bien circulé :

- `DONE` ;
- `SCORE` ;
- `CONCLUSION` ;
- `ARBITRAGE` ;
- rapports métier associés.

Le canal Redis et la corrélation ne sont donc pas absents. La difficulté
observée porte sur la classification et la quantité des échanges.

## Communications non utiles

### Retraitement d'événements déjà clos

Des événements déjà livrés sont retraités comme s'ils ouvraient une nouvelle
obligation :

- `DONE` déjà livré ;
- `SCORE` déjà livré ;
- `CONCLUSION` déjà enregistrée ;
- `ARBITRAGE` déjà livré ;
- `PROTOCOL_ERROR` terminal ;
- anciens turns tardifs ;
- événements `legacy`, `unknown` ou `unattributed`.

Le résultat du tour est alors généralement : état inchangé, aucun fichier
modifié, aucun terminal dû. Le tour modèle a néanmoins été consommé.

### Boucle de surveillance

Le schéma récurrent observé est :

```text
événement déjà livré
→ PROTOCOL RETRY
→ PROTOCOL_ERROR
→ vérification de la livraison existante
→ MASTER_REPORT
→ réception et classification par 334-134
```

Cette boucle produit du trafic sans faire progresser le développement demandé.

### Événements non corrélables

Plusieurs événements contiennent :

- `TASK=unknown` ;
- `CYCLE=unknown` ;
- `CORR=legacy` ;
- `TASK=unattributed`.

Ils ne permettent aucune transition métier fiable. Ils déclenchent pourtant
une lecture, une réponse narrative ou un rapport.

### Double livraison artificielle

Chez `334-834`, certains terminaux tardifs produisent :

1. un `ACK` corrélé pour satisfaire le garde ;
2. un `MASTER_REPORT` sous une nouvelle corrélation.

Le contenu métier reste inchangé, mais deux événements et plusieurs tours sont
générés.

### Rapports sans information nouvelle

Plusieurs rapports indiquent uniquement :

- état inchangé ;
- artefact déjà livré ;
- hash déjà conforme ;
- aucune transition métier ;
- aucun fichier modifié ;
- aucun terminal dû.

Chaque rapport est techniquement livré, mais peut déclencher un nouveau tour
chez le coordinateur.

### Répétition des mêmes diagnostics

La régression du garde est redémontrée plusieurs fois avec les mêmes éléments :

- corrélation déjà close ;
- événement watchdog tardif ;
- aucune action métier due ;
- défaut déjà documenté.

La première occurrence documentée est utile. Les occurrences suivantes
confirment sa persistance mais consomment elles-mêmes les ressources qu'elles
dénoncent.

## Constats par agent

### `334-134`

Point principal d'amplification. Il reçoit et interprète presque tous les
rapports, erreurs, statuts et terminaux tardifs. Une grande partie de ses
réponses conclut qu'aucune action métier n'est nécessaire.

### `334-234`

Produit un audit utile, puis consacre plusieurs tours à confirmer le même faux
positif du watchdog. Son premier rapport apporte de la valeur ; les répétitions
en apportent peu.

### `334-334`

Présente le meilleur ratio de travail métier observable : code et tests réels.
Les relances protocolaires interrompent cependant son exécution et occupent son
contexte.

### `334-534`

L'évaluation R8, son score et son bilan sont utiles. Les vérifications
ultérieures du même score et du même hash n'ajoutent pas de résultat métier.

### `334-734`

La mémoire Curator est déjà livrée et son hash est conforme. Les rapports
ultérieurs constatent principalement cet état inchangé.

### `334-834`

Une part importante de l'activité consiste à écouler des terminaux tardifs,
les acquitter et les rapporter. Six réponses et six relances ont été observées
sans production métier correspondante.

### `334-934`

L'arbitrage initial est utile et étayé. Le rapport supplémentaire provoqué par
un `PROTOCOL_ERROR` tardif ne change pas la décision.

### `334`

L'observation de R8 et du travail Developer est pertinente. L'événement
watchdog `unattributed` reçu ensuite ne porte aucune information métier
actionnable.

## Instructions visibles mais non livrées

Deux instructions apparaissaient dans les composers tmux sans enveloppe bridge
ni preuve de soumission :

- chez `334-234` : redémarrer `voice-agent` et vérifier le full-duplex ;
- chez `334-834` : écouler les terminaux tardifs restants.

Une instruction affichée dans un composer n'est pas un événement métier livré.
Elle ne peut donc pas être comptée comme communication utile exécutée.

## Verdict

| Dimension | Constat |
|---|---|
| Canal technique | Fonctionnel |
| Corrélation | Fonctionnelle |
| État `DELIVERED` | Observable et fréquent |
| Développement réel | Présent, principalement chez `334-334` |
| Tests et preuves | Présents |
| Coordination | Excessivement bavarde |
| Goulot | `334-134` |
| Bruit minimum mesuré | 41 relances sur 135 réponses |
| Bruit supplémentaire | `PROTOCOL_ERROR`, rapports stale, doubles livraisons |
| Effet | Travail utile noyé et contexte consommé |

La difficulté n'est pas l'absence totale de communication. Le système sait
livrer des résultats. Le défaut observable est qu'il déclenche aussi de
nombreux tours pour des événements qui ne devraient produire aucune nouvelle
obligation métier.
