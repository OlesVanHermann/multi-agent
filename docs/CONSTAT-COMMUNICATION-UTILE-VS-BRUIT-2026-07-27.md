# Constat de communication inter-agents : utile vs bruit

Date d'observation : 27 juillet 2026  
Installation observée : Multi-Agent v3.2.11  
Groupe principalement observé : `348-router24-inference`

## Objet et limites

Ce document décrit les échanges entre agents selon leur contribution réelle au
développement demandé par l'utilisateur.

L'observation a porté sur :

- les historiques visibles des sessions tmux `agent-000`, `agent-348` et
  `agent-348-*` ;
- les journaux `logs/<agent>/events.jsonl` ;
- les journaux récents `logs/<agent>/bridge.log`.

L'observation était strictement passive : aucun message n'a été injecté dans
tmux, aucun agent ou service n'a été relancé et aucun comportement n'a été
modifié.

Les nombres issus des journaux représentent des occurrences enregistrées. Ils
ne doivent pas tous être interprétés comme des messages métier uniques, car
certains événements techniques ou payloads sont journalisés plusieurs fois.

## Communication utile au développement demandé

La chaîne de communication métier fonctionne lorsqu'elle suit ce parcours :

```text
demande utilisateur
  → dispatch corrélé
  → travail
  → artefact et tests
  → événement terminal corrélé
  → décision du Master
```

Les échanges utiles observés comportent :

- un `TASK`, un `CYCLE` et un `CORR` stables ;
- un événement attendu explicite ;
- un livrable réel ou une conclusion métier nouvelle ;
- le chemin de l'artefact et son SHA-256 lorsqu'ils existent ;
- le résultat des tests ou l'explication factuelle de leur absence ;
- un terminal `DONE`, `SCORE`, `BLOCKED` ou `INFO_REQUIRED` correspondant au
  travail réellement effectué ;
- une confirmation de livraison `state=DELIVERED`.

### Exemples observés

- `348-548` a produit un bilan de cycle dans
  `bilans/348-cycle4-J-video-34.md`, accompagné de son SHA-256, d'un score et
  de durées mesurées.
- `348-848` a livré le travail Coach de `J-video/34`, avec une candidate
  méthodologique et un `DONE` corrélé.
- Le `DONE` Coach est présent dans l'inbox de `348-148` avec la corrélation et
  le SHA annoncés.
- `348-348` exécute une phase de rejeu métier longue et séquentielle et indique
  son état réel.
- Les agents évitent généralement de réémettre un terminal déjà consommé.
- Lorsqu'une deuxième charge terminale différente est tentée, le bridge la
  refuse avec `terminal slot already consumed by a different payload`. Cette
  protection d'idempotence fonctionne.

Ces échanges font avancer le développement : ils transmettent une décision,
une preuve, un résultat vérifiable ou une information nécessaire à l'étape
suivante.

## Communication sans utilité métier nouvelle

Le bruit dominant est une boucle de clôture centrée sur `348-148` :

```text
PROTOCOL_ERROR
  → réveil d'un agent
  → nouvelle analyse du même défaut
  → report-master.sh BLOCKED
  → création ou rattachement à un tour turn-*
  → nouveau PROTOCOL_ERROR
```

Les réponses produites dans cette boucle répètent principalement :

- « état inchangé » ;
- « aucun changement métier » ;
- « aucun terminal supplémentaire n'est dû » ;
- « boucle persistante » ;
- « attente décision opérateur ou 000 » ;
- `ARTIFACT=NONE` ;
- `TESTS=NOT_RUN` ou `PROTOCOL_LOOP_PERSISTS`.

Ces messages sont techniquement délivrés, mais ils n'apportent aucune
information nouvelle permettant de développer, tester, corriger ou décider.

### Répétitions observées

- `348-248` indique avoir livré une 48e itération du même rapport `BLOCKED`.
- `348-748` renvoie continuellement le même signalement de boucle, sans effet
  métier.
- `348-948` répète que D5 n'est pas déployé et qu'aucun terminal n'est dû.
- `348-348`, pendant un traitement métier long, est régulièrement interrompu
  pour produire un ACK et un `MASTER_REPORT` dont l'état est inchangé.
- `348-848` reçoit plusieurs `PROTOCOL_ERROR` après que son `DONE` a déjà été
  livré et vérifié.

Chaque occurrence mobilise un nouveau tour de modèle pour conclure qu'il
n'existe aucun élément nouveau.

## Volume observé le 27 juillet 2026

Parmi les enveloppes enregistrées dans les journaux des agents :

| Agent | Enveloppes enregistrées | Enveloppes depuis le watchdog |
|---|---:|---:|
| `348-248` | 57 | 55 |
| `348-348` | 233 | 201 |
| `348-548` | 27 | 19 |
| `348-748` | 153 | 146 |
| `348-848` | 21 | 15 |
| `348-948` | 133 | 131 |

Pour `348-248`, `348-748` et `348-948`, la quasi-totalité des enveloppes
observées provient donc du watchdog et non d'un nouveau travail demandé par
l'utilisateur.

Dans les extraits récents de `bridge.log`, les occurrences suivantes ont été
relevées :

| Agent | `PROTOCOL_ERROR` | Terminaux métier relevés |
|---|---:|---:|
| `348-348` | 226 | 2 `DONE` |
| `348-548` | 23 | 5 `DONE`, 2 `SCORE` |
| `348-748` | 294 | aucun dans l'extrait |
| `348-848` | 18 | 4 `DONE` |
| `348-948` | 140 | 4 `DONE` |
| `348-248` | 99 | aucun dans l'extrait |

Ces valeurs mesurent des occurrences textuelles dans les extraits de journaux,
pas nécessairement des événements uniques. Leur disproportion reste néanmoins
significative.

## Autres sources de consommation sans résultat métier

### Événements techniques présentés comme des prompts

Les transitions `xlen N→N+1` sont enregistrées comme des événements de type
`prompt`. Pour `348-148`, 750 occurrences de ce type ont été relevées pendant
la journée observée. Elles décrivent une taille de stream, pas une demande
métier.

### Doubles journalisations et doubles injections

Certains payloads identiques apparaissent deux fois à quelques secondes
d'intervalle. Les journaux montrent aussi des paires identiques de transitions
`xlen`. Cela gonfle le volume apparent et rend la chronologie plus difficile à
lire.

### Recopie systématique de l'enveloppe

L'enveloppe complète est recopiée dans les réponses même lorsqu'aucune réponse
métier n'est due. Cette répétition augmente le contexte consommé sans ajouter
de preuve nouvelle.

### Contradictions temporelles artificielles

Un rapport exact au moment de son émission peut être comparé à un dispatch
arrivé plus tard. Cette comparaison produit alors une contradiction apparente,
suivie de vérifications et de rapports supplémentaires, alors que les deux
états étaient cohérents à leurs instants respectifs.

### Analyse répétée du protocole

Une part importante des tours est consacrée à expliquer pourquoi l'agent ne
doit pas répondre au watchdog, pourquoi le terminal est déjà livré ou pourquoi
la même corrélation ne doit pas être retraitée. Cette analyse est cohérente,
mais ne contribue pas au résultat utilisateur lorsqu'elle est répétée.

## Situation particulière de `348-148`

Le journal de `348-148` contient, pour la journée observée :

- 4 963 événements classés comme prompts ;
- 1 355 enveloppes bridge ;
- 750 transitions `xlen`.

`348-148` reçoit les terminaux métier utiles, mais reçoit également les rapports
produits par les relances watchdog des autres agents. Il devient ainsi le point
de concentration et d'amplification du trafic protocolaire.

## Conclusion factuelle

La communication inter-agents n'est pas globalement cassée. Les fonctions
essentielles suivantes sont observées en fonctionnement :

- dispatch corrélé ;
- livraison d'artefacts ;
- transmission des hashes et des résultats de tests ;
- terminaux métier ;
- livraison au demandeur ;
- protection contre un second terminal divergent.

Le volume dominant ne correspond cependant plus au développement demandé par
l'utilisateur. Il provient de faux défauts de clôture ou de défauts déjà connus
qui déclenchent de nouveaux tours, rapports et confirmations sans changement
d'état.

La distinction observée est donc :

```text
Communication utile
  = information nouvelle + preuve ou décision + étape suivante possible

Communication non utile
  = répétition d'un état connu + aucun artefact + aucun test nouveau
    + aucune décision nouvelle
```

Le principal coût constaté n'est pas l'absence de livraison métier, mais
l'amplification automatique de messages de contrôle après que la livraison a
déjà eu lieu. Cette amplification interrompt les travaux longs, augmente la
taille des contextes et consomme des tours de modèle sans progresser vers le
résultat demandé par l'utilisateur.
