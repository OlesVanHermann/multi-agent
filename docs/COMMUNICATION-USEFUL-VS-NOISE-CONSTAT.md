# Constat des communications inter-agents : utile vs non utile

## Périmètre

Ce document consigne uniquement les observations réalisées sur les échanges
postérieurs à l'upgrade v3.2.11, entre le 27 juillet 2026 à 11:47 UTC et
environ 16:36 UTC.

L'objectif de l'analyse est de distinguer :

- les communications qui font progresser le développement demandé par
  l'utilisateur ;
- les communications techniques, répétitives ou circulaires qui n'apportent
  aucun nouvel élément métier.

Cette analyse est un constat. Elle ne contient ni modification du système, ni
proposition de correction, ni plan d'action.

## Données observées

Sur la période :

- 4 722 événements ont été classés `prompt` ;
- 2 442 enveloppes de communication inter-agents ont été observées ;
- 2 197 événements `xlen` ont été enregistrés ;
- 187 événements `api_error` ont été enregistrés ;
- 435 enveloppes mentionnaient le watchdog.

Les journaux ne fournissent pas le coût en tokens de chaque message. Ils
permettent donc de mesurer le volume et les répétitions, mais pas d'établir un
ratio exact de tokens utiles et inutiles.

## Communications utiles

Une communication est considérée utile lorsqu'elle apporte au moins un nouvel
élément nécessaire à l'exécution de la demande utilisateur :

- une mission ou un périmètre précis ;
- une source ou un fichier autoritatif ;
- un commit ou un artefact ;
- un résultat de compilation ou de test ;
- un blocker vérifiable ;
- une décision d'arbitrage ;
- une preuve nouvelle.

La chaîne de développement fonctionne effectivement :

1. le Master transmet une tâche identifiée avec son cycle et sa source ;
2. le Developer reçoit une demande d'implémentation ou de correction bornée ;
3. l'Integrator communique un commit ou un résultat de build ;
4. le Tester reçoit un artefact déterminé et produit un résultat ;
5. le statut utile remonte avec une preuve ou un blocker.

Exemples observés :

- `303-103 → 303-303` : développement des tests MinIO de production avec
  source autoritative ;
- `303-103 → 303-303` : correction C2 limitée à deux blockers ;
- `303-303 → 303-103` : gate d'intégration avec
  `cargo build --workspace` réussi ;
- `303-303 → 303-103` : diagnostic d'un test de déploiement bloqué avec sa
  cause ;
- `303-103 → 303-703` : préparation d'un brief et d'artefacts ;
- `304-104 → 303-103` : clôture de SPEC avec statut métier ;
- `305-105 → 305-305` : implémentation d'un lot depuis un artefact projet ;
- `305-105 → 305-505` : évaluation d'un correctif identifié par commit.

Ces échanges participent directement à l'analyse, au développement, à
l'intégration ou à la validation du résultat demandé par l'utilisateur.

## Communications sans valeur métier nouvelle

Le bruit principal est constitué de confirmations terminales réciproques.

### Boucle `304-104 ↔ 304-904`

Sur les 2 442 enveloppes observées :

- 468 allaient de `304-104` vers `304-904` ;
- 324 allaient de `304-904` vers `304-104` ;
- cette paire représente 792 enveloppes, soit environ 32 % du total.

Pendant de longues séquences, ces agents échangeaient toutes les 30 à
50 secondes des variantes de statuts déjà acquis :

- `DONE consommé` ;
- `TERMINAL_DONE_CONSUMED` ;
- `FINAL_DONE_RECONCILED_CONSUMED` ;
- `STATUS_RECONCILED_CONSUMED` ;
- `déjà DELIVERED` ;
- `corrélation CLOSED` ;
- `réconciliation watchdog consommée` ;
- `réponse non terminale livrée après DONE`.

Ces messages ne contenaient généralement ni nouveau code, ni nouvelle preuve,
ni décision nouvelle. Une confirmation déclenchait une nouvelle réponse, qui
était ensuite elle-même traitée comme un nouveau tour à terminer.

### Faux signaux dans le triangle `305`

Les volumes principaux vers `305-105` étaient :

- 304 enveloppes depuis `305-205` ;
- 250 depuis `305-805` ;
- 196 depuis `305-905` ;
- 141 depuis `305-305`.

Le watchdog a également produit plusieurs centaines de notifications vers ce
triangle.

Des réponses de `305-205` qualifient explicitement les alertes reçues de faux
positifs, notamment les occurrences numérotées 112, 113 et 114 de la même
classe de `PROTOCOL_ERROR`.

`305-905` signale de son côté :

- `Repeated watchdog recursion` ;
- `Recursive PROTOCOL_ERROR` ;
- `Repeated watchdog false positive` ;
- `Known recursive PROTOCOL_ERROR`.

Le diagnostic du faux positif est lui-même transmis au Master et devient un
nouvel échange consommé par le modèle, sans progression métier.

### Événements tardifs et fins de tour

Les journaux montrent aussi les séquences suivantes :

1. un terminal `DONE` est livré et consommé ;
2. un événement tardif arrive sur la corrélation fermée ;
3. l'agent répond que l'événement est tardif ou déjà consommé ;
4. cette réponse est interprétée comme un nouveau tour ;
5. un nouveau terminal ou un rappel de fin de tour est produit.

Les rappels `PROTOCOLE DE FIN DE TOUR`, les états `LATE_EVENT`, les accusés
après terminal et les réconciliations successives décrivent alors l'état du
protocole sans apporter de résultat supplémentaire à l'utilisateur.

## Cas des événements `xlen`

Les 2 197 événements `xlen N→N+1` représentent une part importante des
événements classés `prompt`.

Ils ne sont cependant pas retrouvés comme messages `Sending to Claude` dans
les journaux des bridges examinés. Les preuves disponibles les présentent
comme des événements internes de monitoring classés dans la mauvaise
catégorie, et non comme des communications inter-agents.

Ils polluent donc les statistiques de prompts. Les journaux observés ne
permettent pas d'affirmer qu'ils consomment eux-mêmes des tokens modèle.

## Effets constatés

Les communications utiles permettent bien de développer ce que l'utilisateur
a demandé. Elles transportent les missions, sources, commits, tests, blockers
et preuves nécessaires.

En parallèle, les communications sans valeur métier :

- augmentent fortement le nombre de tours ;
- maintiennent certains agents occupés sur des corrélations déjà closes ;
- provoquent de nouvelles vérifications de protocole ;
- participent aux reprises et compactages de contexte ;
- rendent le trafic de contrôle majoritaire sur les agents les plus actifs ;
- masquent les rares messages contenant une information nouvelle.

Les 792 enveloppes de la seule paire `304-104 ↔ 304-904` démontrent qu'une part
substantielle du trafic est indépendante de la production du résultat métier.
Le triangle `305` ajoute plusieurs centaines de messages liés aux faux
`PROTOCOL_ERROR`, aux événements tardifs et aux rapports récursifs.

## Conclusion

Le transport inter-agents fonctionne : les tâches, résultats, commits,
preuves et blockers atteignent leurs destinataires.

Le problème observé ne réside pas dans l'absence de communication utile, mais
dans son enfouissement sous un volume supérieur de communication de contrôle.
Les boucles d'accusés terminal/réconciliation, les faux signaux du watchdog et
le traitement des événements tardifs comme de nouveaux tours représentent la
principale communication sans valeur pour le développement demandé par
l'utilisateur.

Le ratio exact en tokens ne peut pas être établi à partir des journaux
disponibles. En volume de messages, le trafic non métier est manifestement
majoritaire sur les paires les plus actives.
