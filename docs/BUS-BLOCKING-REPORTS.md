# Bus des blocages — constats et invariants

## Défauts corrigés

L'incident observé sur le triangle 334 n'était pas une panne Redis. Le canal
`report-master.sh` persistait les comptes rendus dans un stream volontairement
silencieux. Une question bloquante pouvait donc attendre le prochain prompt
opérateur avant d'atteindre le Master.

Le premier réveil à chaud a révélé les défauts connexes suivants :

1. rapport, réveil et hash d'état étaient trois écritures séparées ;
2. un échec partiel suivi d'un retry pouvait dupliquer le rapport ou le réveil ;
3. un `BLOCKED`/`INFO_REQUIRED` dérivé était reclassé comme terminal puis
   réannexé avec son rapport, jusqu'à trois copies dans un seul prompt ;
4. la déduplication utilisait le texte mutable et omettait l'identité du tour ;
5. deux tours au texte identique pouvaient se neutraliser pendant que deux
   reformulations du même tour pouvaient réveiller deux fois ;
6. `done.sh` ne transportait pas le `turn_id` et ne partageait aucun slot avec
   `report-master.sh` ;
7. `SOURCE_CORR=none` et les métadonnées absentes rendaient les traces ambiguës ;
8. le réveil de supervision pouvait satisfaire à tort la garde de livraison
   métier ;
9. `DELIVERED` décrivait une écriture Redis, pas une consommation ;
10. les tests vérifiaient des chaînes de source au lieu du comportement réel.

## Invariants du correctif

- Un rapport logique existe au plus une fois par émetteur et tour.
- Un rejeu identique ne crée aucune nouvelle entrée ; un payload différent sur
  le même ID est un conflit explicite sans mutation.
- `SUCCESS`, `PARTIAL` et `FAILED` restent silencieux.
- `BLOCKED` et `INFO_REQUIRED` produisent au plus un `DECISION_REQUIRED` par
  décisionnaire, émetteur et tour.
- `done.sh`, `send.sh` et `report-master.sh` utilisent la même identité de
  décision quand ils décrivent le même blocage.
- Un nouveau `source_turn_id` autorise une nouvelle décision, même avec la même
  corrélation et le même texte.
- Un rapport ne clôt jamais une obligation métier.
- Le prompt du Master contient une seule représentation de la décision ; les
  autres objets restent disponibles pour l'audit hors contexte modèle.
- Les types Redis sont validés avant toute écriture atomique.
- Aucun champ de corrélation nominal ne prend la valeur littérale `none`.

## Constat du 19/08/2026 — livré n'est pas lu (A8)

Après le correctif de livraison inconditionnelle, un rapport `PARTIAL` de
`334-334` atteignait bien l'inbox de `334-134`… où le classificateur le
rangeait en `:supervision` « stored; not injected into TUI ». Le Master,
idle depuis 13:26, n'a ouvert aucun vrai tour : 11 messages stockés entre
14:11 et 18:04, zéro lu. Trois causes conjuguées :

1. la lecture dépendait d'un « prochain vrai tour » jamais garanti ;
2. le bridge de `334-134` exécutait un code chargé le 29/07 pendant que les
   correctifs des 18-19/08 attendaient sur disque ;
3. les rapports post-tour partaient en `TASK=unattributed`/`CORR=rescue-*`
   car le bridge efface l'enveloppe (`current_*`) à la fin du tour alors que
   le modèle travaille encore.

Invariants ajoutés :

- un contenu parqué est annexé au prochain vrai tour OU à un tour de
  synthèse ouvert par le bridge après `ANNEX_FLUSH_IDLE_S` d'inactivité —
  la lecture a une échéance ;
- un contenu présenté au modèle reçoit un accusé `ma:bus:v1:read:*` ;
  le watchdog alerte (`unread_backlog`) au-delà de `UNREAD_DEADLINE_S` ;
- l'enveloppe du tour survit à sa fin (`last_*`, fraîcheur bornée par
  `MA_LAST_TURN_CONTEXT_TTL`) ; le tour lui-même n'est jamais hérité, la
  déduplication des rapports reste par tour ;
- chaque bridge publie l'empreinte de son code chargé ; le watchdog signale
  `STALE_BRIDGE` et `agent.sh reload-bridge` recharge le bridge sans toucher
  le moteur ;
- un texte stable dans un composer idle au-delà de `COMPOSER_ORPHAN_S`
  déclenche une alerte (jamais d'auto-submit) : une saisie tmux directe
  n'est pas une livraison.

## Constat du 22/08/2026 — le rejeu de terminal était scopé au tour (A9)

Un `done.sh` émis hors-tour (enveloppe bridge effacée → tour fabriqué) puis
rejoué dans le tour suivant portait deux `source_turn_id`, donc deux
`event_id` : le rejeu strict passait pour un NOUVEAU terminal. Observé sur
`334-334` → `334-134` : deux `DONE` au texte identique, deux tours Master
consommés pour la même livraison, à 107 s d'écart.

Invariant ajouté : chaque terminal possède un **slot logique indépendant du
tour** — `ma:bus:v1:terminal-slot:<id>` dérivé de
(émetteur, cible, événement, tâche, cycle, corrélation), avec une empreinte
de contenu qui exclut le tour et l'origine. Quel que soit le tour :

- rejeu au contenu identique → `ALREADY_DELIVERED`, aucune écriture, la
  livraison ORIGINALE est retournée (event_id du premier envoi) ;
- même slot, contenu différent → `NOT_DELIVERED`, réémission après ouverture
  d'un nouveau `CYCLE`/`CORR` (un nouveau `TURN` ne suffit plus).

Les terminaux émis avant ce correctif n'ont pas de slot logique : leur
premier rejeu inter-tours peut encore livrer une fois, les suivants sont
dédupliqués (même transition que les anciens slots pré-`ma.bus.v1`).

## Déploiement à chaud

Les scripts shell sont relus à chaque invocation et ne nécessitent aucun
redémarrage. Le bridge Python déjà chargé continue cependant d'exécuter son
ancien code jusqu'à son prochain redémarrage manuel. Le patch est donc sûr à
installer sans redémarrer, mais la déduplication consumer et le filtrage des
annexes ne sont complets qu'après la fenêtre de reload choisie par l'opérateur.

Les anciens slots de déduplication ne sont pas convertis en `ma.bus.v1` : ils
ne contiennent pas assez d'identité pour déduire sans ambiguïté leur cible. Un
agent qui rejoue manuellement, après l'upgrade, une commande déjà publiée par
l'ancien protocole peut donc la republier une fois. Les rejeux suivants sont
idempotents dans le nouveau schéma.
