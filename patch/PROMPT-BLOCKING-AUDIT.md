# Audit des blocages d'exécution causés par les prompts

Date : 2026-07-18
Périmètre : 59 sessions tmux actives, 229 `*-memory.md`, 229 `*-system.md`,
224 `*-methodology.md`, loader canonique et templates x45.

## Conclusion

Le problème n'est pas un manque d'instructions d'exécution. Il vient de règles
anciennes formulées comme des absolus qui contredisent le contrat plus récent de
priorité utilisateur. Les agents choisissent alors l'interprétation la plus
restrictive : ils émettent `INFO_REQUIRED`, demandent un arbitrage ou restent
idle, même lorsque la demande opérateur et l'état physique suffisent.

## Moments observés dans tmux

| Triangle | Moment | Blocage observé | Origine prompt |
|---|---|---|---|
| 380 | Phase C de `01-backend-file-logging` | Dev, Observer et Master déclarent la tâche prête mais Phase C reste bloquée par arbitrage 000. | `380-180-system.md` autorisait **AUCUN** fichier tout en exigeant `mkdir/cp/mv`, puis demandait un `rm -f` interdit globalement. |
| 385 | `feature-contextes-p4-ui` | Score 96, Vitest/tsc/Vite verts et commits vérifiés ; clôture retardée par fichiers concurrents hors scope, absence de `A-agent-100`, hash de bilan mis à jour et cible `cli` rejetée. | Phase C exigeait « zero fichier untracked dans aiapp/frontend » et signal obligatoire à 100. Le contrat de corrélation était traité comme plus important que le résultat vérifiable. |
| 373 | `b-transfer-folder-upload-nofile` | Le port CDP 9222 est indisponible ; le Developer conclut qu'aucun diagnostic ou code n'est autorisé et demande une preuve manuelle opérateur. | Memory : « CDP EN PREMIER », « aucun code avant preuve PRE », « sans opérateur rester bloqué ». Un gate d'observation devient gate d'exécution total. |
| 386 | reprise de task-107 et messages de relecture | Multiples `INFO_REQUIRED` ou `PROTOCOL_ERROR` pour TASK/CYCLE/CORR inconnus, requête SCORE redirigée, livraison `cli` considérée impossible. | Métadonnées bridge appliquées à une commande directe ; memory historique traitée soit comme autorité absolue, soit comme totalement inutilisable, sans voie médiane de réconciliation. |
| 388 | reprise Task 91 | Dev/Master/Observer échangent des terminaux `unknown`, restent idle et attendent une spec ou un arbitrage alors que les artefacts et l'ancien cycle existent. | Interdiction d'inférer la tâche et absence de règle forte donnant priorité à la demande utilisateur directe et à l'artefact physique. |
| 334/371/385/386/388 | demande `relis tes prompts` | Travail souvent exécuté, puis agents tentent `send.sh cli`; le script refuse l'ID et l'agent considère la livraison incomplète. | Aucun traitement canonique de `FROM=cli` dans l'ancien loader. |

## Contradictions racines

1. « Tu ne fais QUE ce qui est décrit dans system.md » contredit « instruction
   utilisateur la plus récente = priorité 1 ».
2. « UNIQUEMENT les informations de memory.md » contredit la réconciliation
   avec l'état physique et rend toute nouvelle demande impossible par définition.
3. « Tu ne fais pas le travail d'un autre agent » est interprété comme un refus
   de la demande utilisateur, même lorsque l'agent possède déjà les outils et le
   processus nécessaires.
4. Les whitelists de fichiers décrivent parfois le code métier, mais oublient
   les mutations transactionnelles du workflow (`TODO/DOING/DONE`, artefacts,
   memory d'état).
5. Les gates de qualité sont écrits « non deferable » sans distinguer :
   exécution, validation partielle, clôture et preuve interactive.
6. Les métadonnées de corrélation, destinées au routage inter-agent, deviennent
   une bureaucratie bloquante pour les ordres directs.
7. Les contrôles de propreté portent sur le worktree global plutôt que sur le
   diff et les fichiers de la tâche, bloquant les travaux concurrents légitimes.

## Politique de correction

### À appliquer à toutes les memories

- La memory est un contexte préparé, non exhaustif et potentiellement périmé.
- Une ancienne section « tâche courante : aucune » signifie seulement qu'aucune
  tâche ancienne ne doit être réactivée spontanément ; elle n'annule jamais une
  nouvelle instruction utilisateur.
- Les contraintes techniques restent des garanties à réutiliser. Les anciens
  noms de tâche, cycles, hashes, listes de fichiers et états d'agents sont des
  observations à réconcilier, pas des motifs automatiques de refus.
- Écrire les gates sous la forme : preuve préférée, alternative sûre, résultat
  `NOT_RUN`, puis impact exact sur la clôture. Éviter « aucun code avant preuve »
  sauf risque destructif ou choix irréversible entre plusieurs cibles.

### À appliquer aux systems Master

- Autoriser explicitement les fichiers transactionnels du workflow.
- Mesurer la propreté sur le périmètre de la tâche, jamais sur tout le worktree.
- L'absence d'un Master global empêche la notification inter-agent, pas la
  clôture ni la réponse à l'utilisateur.
- Après dispatch, attendre l'événement bridge ; supprimer les boucles
  `sleep → tmux → retry` contradictoires avec le loader.

### À appliquer aux systems Developer

- Le scope Curator est le point de départ minimal. Une demande utilisateur peut
  l'étendre dans le même projet/rôle sans arbitrage, après inspection de l'état
  réel et avec une liste de fichiers réellement modifiés.
- Refuser uniquement les frontières fortes : secrets, autre projet/triangle,
  prompts non autorisés, action destructive ou infrastructure hôte hors mandat.

### À appliquer aux Observer/Curator/Coach/Architect

- Un artefact existant et vérifiable prime sur une ancienne corrélation.
- Un hash devenu ancien après une mise à jour normale se recalcule et se signale ;
  il ne transforme pas une décision identique en second résultat métier.
- Une relecture sans nouvelle tâche ne doit pas générer une chaîne circulaire
  d'`INFO_REQUIRED`. Répondre directement à l'opérateur puis rester idle.

## Patch framework

Voir `patch/PROMPT-EXECUTION-PRIORITY.md`. Le test de non-régression est
`tests/test_prompt_operator_priority.py`.

## Changements projet préparés

- Triangle 380 : permissions Phase A/C cohérentes, archivage sûr, suppression du
  polling actif.
- Triangle 385 : propreté limitée au périmètre, 100 facultatif pour une demande
  directe, suppression du polling actif.
- Triangle 373 : CDP préféré mais dégradable ; diagnostic/code/tests indépendants
  continuent et l'interactif devient `NOT_RUN` si indisponible.

## Validation recommandée après déploiement

1. Injecter à un agent idle une demande utilisateur hors de son ancienne tâche
   mais dans son projet/rôle : il doit exécuter, pas répondre « hors mission ».
2. Injecter une commande avec `FROM=cli` et sans TASK/CYCLE/CORR : elle doit être
   exécutée et la réponse apparaître dans le TUI.
3. Rendre CDP indisponible : le cycle doit poursuivre les preuves indépendantes
   et produire `NOT_RUN`, sans attente opérateur infinie.
4. Ajouter un fichier concurrent hors scope : Phase C doit vérifier uniquement
   le diff de la tâche et se clôturer.
5. Arrêter l'agent 100 : le triangle doit livrer le résultat à l'utilisateur et
   noter seulement que la notification globale n'a pas été routée.
