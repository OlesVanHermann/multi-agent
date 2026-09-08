# Constat des échanges inter-agents — utile vs non utile

Date de l'observation : 2026-07-27
Périmètre : triangle `300`, principalement `300-100`, `300-200`,
`300-300`, `300-500`, `300-700`, `300-800` et `300-900`.

Ce document est un constat en lecture seule. Il ne prescrit aucune correction
et ne modifie ni le runtime, ni les prompts, ni les services.

## Finalité utilisateur observée

Les échanges analysés concernent le développement et la validation du cycle de
vie des sessions : lancement réel depuis l'interface, fonctionnement de la VM,
signalisation, vidéo et contrôle d'entrée, arrêt durable, traitement de la
fuite de credential TURN, puis validation sur une seconde cible.

Le résultat demandé n'est que partiellement atteint :

- un premier lancement réel a été observé avec HTTP 200, VM, signalisation,
  vidéo et input ;
- l'exécution s'est ensuite arrêtée sur le gate de sécurité lié au credential
  TURN ;
- une correction TURN et ses tests ont été annoncés, mais sa promotion et son
  déploiement ne sont pas démontrés par les échanges ;
- la seconde cible et le cycle complet ne sont pas validés ;
- aucun `DONE` global abusif n'a été publié pour déclarer ce résultat complet.

## Communications utiles

Les échanges utiles apportent un résultat métier, une preuve nouvelle, un
verdict ou une décision exploitable :

- `300-300` a livré à `300-100` un `DONE` corrélé pour la tâche
  `203-bounded-session-recovery-and-control-plane-closure` à 09:47:40 ;
- ce terminal annonce la correction de la fuite de credential TURN, des hashes
  d'artefacts et 106 tests réussis ;
- `000` a livré deux arbitrages corrélés ;
- `300-200` a produit et livré un audit consolidé à `300-100` ;
- cet audit distingue le succès physique du premier lancement, l'arrêt
  fail-closed sur TURN, l'absence de seconde cible et l'absence de promotion de
  la candidate ;
- les enveloppes, corrélations et états `DELIVERED` montrent que le canal
  Redis/bridge transporte effectivement les résultats métier.

La communication utile existe donc et les résultats ne sont pas perdus.

## Communications non utiles

Le trafic récent est dominé par une récursion de contrôle :

```text
PROTOCOL_ERROR watchdog
  → analyse par un worker
  → MASTER_REPORT forcé vers 300-100
  → nouveau tour chez 300-100
  → absence d'événement métier attendu
  → nouveau PROTOCOL_ERROR
```

Sur le journal courant de `300-100`, démarré à 09:29:39 :

- 751 messages entrants ont été observés ;
- 140 proviennent directement du watchdog ;
- seulement trois terminaux métier sont clairement identifiables dans les
  lignes entrantes : un `DONE` et deux `ARBITRAGE` ;
- au moins 283 messages sont directement classables comme trafic de contrôle
  répétitif ;
- 143 rapports d'agents mentionnent explicitement une relance, une boucle, un
  écho, une récidive ou un `PROTOCOL_ERROR`.

Sur les 250 derniers messages reçus par `300-100` au moment du relevé :

- 83 viennent du watchdog ;
- 167 sont des rapports d'agents ;
- aucun n'est un nouveau terminal métier utile.

Le cas le plus visible est `300-300` :

- 370 messages watchdog reçus dans son journal courant ;
- l'agent qualifie lui-même un tour de « trois-cent-soixante-sixième écho
  identique » ;
- les tours répétés durent souvent de 10 à 27 secondes ;
- ils redisent que le `DONE` est déjà livré, que l'état n'a pas changé et
  qu'aucun déploiement n'a eu lieu.

Ces tours consomment du contexte et des appels modèle sans produire de code,
de test nouveau, de preuve physique supplémentaire ou de décision.

## Constat par rôle

### 300-100 — Master

Le Master reçoit correctement les terminaux et rapports. Il classe souvent les
rejeux comme bruit et évite les ACK terminaux inutiles. Néanmoins, chaque
message injecté dans son TUI déclenche encore un tour modèle, même lorsque sa
seule conclusion est qu'aucune action n'est due.

### 300-200 — Contradictor

Son audit consolidé est utile : il rétablit la demande utilisateur, les preuves
physiques, les gates non franchis et l'état réel du résultat. Autour de cet
audit, il reçoit également de nombreux tours watchdog sans information
nouvelle.

### 300-300 — Developer

Le développement initial et le `DONE` de la tâche 203 sont utiles. La très
grande majorité de ses échanges ultérieurs répète le même diagnostic et le
même état d'artefact uniquement pour satisfaire le contrôle de fin de tour.

### 300-500 — Tester

Les échanges récents portent principalement sur l'impossibilité d'adresser une
réponse à `watchdog` et sur la récursion du protocole. Ils ne produisent plus de
validation nouvelle du besoin utilisateur.

### 300-700 — Curator

L'agent identifie correctement la récursion et évite parfois de répéter une
tentative déjà vouée à l'échec. Ses rapports de blocage restent cependant
injectés chez le Master.

### 300-800 — Coach

L'agent essaie explicitement de ne rien émettre lorsque l'information est déjà
connue. Le Stop hook refuse alors la fin du tour et le force périodiquement à
publier un nouveau `MASTER_REPORT`, qui alimente la récursion.

### 300-900 — Observer

L'agent classe correctement certains événements watchdog comme terminaux sans
réponse attendue. Son bridge actif continue néanmoins à lui injecter des
rappels issus de la logique chargée au démarrage.

## Écart entre activité et progrès

L'activité des agents est élevée, mais elle ne correspond pas à une progression
équivalente du livrable :

- les corrélations et livraisons fonctionnent ;
- le même incident de protocole génère des centaines de tours ;
- les rapports répètent des preuves et hashes inchangés ;
- aucun nouveau lancement de session, test de seconde cible ou déploiement
  n'apparaît dans la fenêtre récente ;
- le canal qui devrait porter les décisions et résultats est majoritairement
  occupé par l'observation de son propre dysfonctionnement.

## Conclusion

La communication inter-agents est techniquement opérationnelle : les messages
sont livrés, consommés et corrélés, et les terminaux métier utiles atteignent
le Master.

Son efficacité pour accomplir la demande utilisateur est cependant faible sur
la période récente. Après le résultat utile de la tâche 203, le trafic devient
principalement autoréférentiel. Les agents dépensent davantage de tours à
signaler qu'aucune information nouvelle n'existe qu'à développer, déployer et
valider le cycle de sessions demandé.

Le besoin utilisateur reste partiellement réalisé : premier lancement observé,
mais correction TURN non démontrée en production, seconde cible non validée et
cycle complet non prouvé.
