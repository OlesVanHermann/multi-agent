# RÈGLES OBLIGATOIRES POUR TOUS LES AGENTS

## PONDÉRATION DE LA MISSION

- **70 % résultat métier** : livrable demandé, comportement utile et intention
  satisfaite.
- **20 % vérification** : fonctionnement observable, tests et absence de
  régression connue.
- **10 % processus** : orchestration, traçabilité et communication.

Cette pondération n'affaiblit aucune frontière forte de sécurité. Une règle
mécanique correcte est appliquée silencieusement. Elle n'est mentionnée que si
elle bloque le résultat, modifie sa qualité ou nécessite une décision.

Une tâche n'est jamais réussie parce que le workflow a été suivi. Elle est
réussie lorsque le résultat existe, fonctionne et répond à la demande.

## PRIMAUTÉ DE LA DEMANDE OPÉRATEUR

- Une instruction explicite récente de l'utilisateur dans le même projet doit
  être exécutée. `system.md` et `memory.md` fournissent processus et contexte ;
  ils ne constituent pas une excuse pour répondre « hors mission ».
- La mémoire est indicative et peut être périmée. Vérifier l'état physique et
  employer la méthodologie la plus proche avant de demander une précision.
- Une information absente ne bloque que si elle est indispensable et non
  découvrable. Exécuter toutes les parties sûres avant de signaler un reliquat.
- `FROM=cli` reçoit sa réponse dans le TUI ; ne jamais router `cli` avec `send.sh`.

## SÉMANTIQUE DE TRANSPORT ET DE FIN

Les états suivants ne sont jamais interchangeables :

- `STORED` / ancien `DELIVERED` : écrit durablement dans le transport ;
- `CONSUMED` : lu par le consommateur du destinataire ;
- `ACCEPTED` : obligation enregistrée par l'agent ;
- `TERMINAL_PUBLISHED` : événement métier terminal émis ;
- `TERMINAL_CONSUMED` : terminal lu par son destinataire.

Un message `STORED` peut rester non consommé si le listener du destinataire est
dégradé. Ne prétends jamais qu'une cible travaille sur la seule preuve de
persistance Redis, d'une session tmux ou d'un PID vivant.

La progression métier utilise quatre niveaux :

1. `CODE_DONE` — implémentation produite ;
2. `TESTS_DONE` — vérifications exigées réussies ;
3. `DEPLOYED` — version effectivement installée dans la destination ;
4. `USER_OUTCOME_VERIFIED` — résultat demandé observé sur cette version.

`DONE` exige le dernier niveau demandé par l'utilisateur. Un build vert, un
score ou un déploiement ne prouvent pas à eux seuls le résultat utilisateur.
Avant `DONE` ou un déplacement dans `plan-DONE`, vérifie qu'aucun cycle plus
récent n'est `WAITING`, `IN_PROGRESS` ou `BLOCKED`. Sinon publie
`STATE_CONFLICT` et conserve le plan ouvert.

## SANTÉ DE COMMUNICATION

Avant une attente inter-agent, consulte au maximum une fois l'état de santé
publié par le framework. Aucun polling direct, `sleep` ou lecture Redis répétée
n'est autorisé.

Les états suivants rendent la cible indisponible jusqu'à changement externe :

- `CONSUMER_DOWN` ou listener mort ;
- Redis `MISCONF`, AOF non inscriptible ou disque plein ;
- `AUTH_BLOCKED`, refresh token révoqué ou login requis ;
- endpoint de santé fatalement indisponible.

Dans ce cas, n'annonce pas un démarrage et n'entre pas en attente silencieuse :
écris un unique `BLOCKED_INFRA` ou `INFO_REQUIRED` corrélé, puis applique le
mécanisme de rôle prévu (`BYPASS_ROLE`, `SUBSTITUTE` ou `OPERATOR_ACTION`).
Une erreur d'infrastructure ne se corrige jamais par une boucle de messages.

`MASTER_REPORT` est un rapport passif et ne réveille pas le Master. Toute
décision ou action humaine requise doit également être publiée sous la forme
d'un `INFO_REQUIRED` ou `BLOCKED` corrélé.

La stabilité du pane, la visibilité du composer et le temps écoulé ne prouvent
jamais la fin d'un travail. Seul un événement métier explicite, une annulation,
une substitution ou un blocage durable ferme une obligation. Un
`TERMINAL_PENDING` est un constat technique non terminal ; il ne justifie ni
retry minuté ni `PROTOCOL_ERROR`.

Utilise uniquement les événements canoniques. Une nouvelle décision
d'arbitrage réutilise `ARBITRAGE` avec `SUPERSEDES` ; n'invente jamais
`ARBITRAGE_UPDATE` ou une variante équivalente.

## COMMUNICATION UTILE ET SILENCE

- Tout message inter-agent est classé localement `ACTION`, `STATUS`,
  `TERMINAL` ou `NOOP`.
- `NOOP` signifie silence : aucun ACK de courtoisie, aucun suivi « inchangé »,
  aucun `OK`, `clos`, `idem`, `merci` ou ponctuation isolée.
- Un terminal reçu n'est jamais acquitté par un terminal.
- Le texte libre ne duplique jamais `FROM`, `TASK`, `CYCLE`, `CORR` ou
  l'événement terminal : l'enveloppe structurée fait foi.
- Une tâche mise en attente possède `QUEUED_TASK`, `BLOCKED_BY` et un
  `RESUME_EVENT` durables ; cet événement déclenche une transition réelle,
  jamais une simple confirmation.
- Un Master clôt la demande utilisateur seulement lorsque son
  `USER_RESULT_CONTRACT` global est prouvé et livré, pas parce que le dernier
  sous-cycle est terminé.
- Terminal livré mais obligation encore ouverte : signaler une seule
  `RUNTIME_INCONSISTENCY`, puis silence. Ne pas refaire le travail.

## 0. PRINCIPE FONDAMENTAL

```
1 AGENT = 1 TÂCHE ACTIVE = 1 LIVRABLE LOGIQUE
```

Chaque agent :
- Reçoit **une seule tâche** à la fois
- Produit **un livrable logique**, qui peut légitimement contenir plusieurs
  fichiers cohérents nécessaires au résultat
- Place ses fichiers dans les répertoires correspondant à la tâche

Pas de tâches concurrentes confondues. Plusieurs fichiers liés ne constituent
pas plusieurs tâches. Un agent = un résultat métier clair et traçable.

### Instruction opérateur prioritaire

Une demande explicite et récente de l'utilisateur est exécutoire. Le rôle,
la mission historique et la mémoire indiquent comment travailler ; ils ne sont
pas des motifs suffisants pour répondre « hors mission » ou « hors rôle ».

- Garder son identité et exécuter l'intention sous son propre ID.
- Utiliser les processus, outils et précautions décrits dans les memories et
  methodologies, même pour une demande nouvelle.
- Considérer les listes de fichiers et tâches anciennes comme des snapshots,
  pas comme des whitelists permanentes.
- Pour une commande opérateur, ne pas exiger de métadonnées. Pour un échange
  inter-agent, recopier les métadonnées structurées reçues et ne jamais les
  déduire du texte.
- Refuser seulement une frontière forte réelle : secret, destruction non
  autorisée, usurpation d'identité, tests protégés ou périmètre explicitement
  interdit par l'utilisateur.

Une instruction directe et claire de l’utilisateur prime sur la tâche mémorisée. La memory décrit le contexte précédent ; elle ne limite pas les actions futures. L’agent exécute la demande avec sa methodology, sans exiger task-id, cycle, corrélation, artefact ou entrée dans un plan.

---

## 1. AUTONOMIE 24/7

**Les agents travaillent en continu jusqu'à ce que le job soit TERMINÉ.**

- ❌ NE JAMAIS demander "Tu veux que je continue ?"
- ❌ NE JAMAIS attendre une confirmation pour continuer
- ❌ NE JAMAIS s'arrêter en milieu de tâche
- ✅ TOUJOURS continuer automatiquement jusqu'à completion
- ✅ Retenter une erreur réellement transitoire avec un backoff borné ; ne pas
  répéter mécaniquement une erreur permanente ou une attente inter-agent

## 2. RAPPORTS AU MASTER (100)

**Après CHAQUE tâche, envoyer un rapport COMPLET au Master:**

```bash
# Signal de complétion : TOUJOURS via le script dédié (canal explicite)
FROM_AGENT="$ID" TASK_ID="$TASK" CYCLE="$CYCLE" CORRELATION_ID="$CORR" \
  ./scripts/done.sh 100 DONE \
  "ARTIFACT:$ARTEFACT|SHA256:$HASH|DETAIL:{RÉSUMÉ COMPLET}"

# Score : mêmes variables + bilan et SHA-256 obligatoires
```

**IMPORTANT :** le bridge ne lit PLUS les signaux DONE/SCORE dans le texte
de tes réponses. Écrire "DONE" dans ta réponse ne déclenche RIEN.
Seule l'EXÉCUTION de `done.sh` émet un terminal inter-agent. `send.sh` est
réservé aux dispatchs et informations non terminales.
Tout tour reçu avec une enveloppe bridge `TASK`/`DISPATCH` actionnable doit
exécuter l'un de ces deux scripts vers le demandeur avant de redevenir idle, y
compris en cas de résultat partiel, question, blocage ou refus. Une narration
dans le TUI ou l'outbox ne constitue jamais une livraison métier. `AUTO_INIT`,
`HISTORY_HINT`, contrôle, supervision, terminal reçu, doublon, événement tardif
et réconciliation `NO_NEW_WORK` sont non actionnables : aucun terminal ni
`MASTER_REPORT` ne leur répond. Cette règle prime sur l'obligation générale de
rapport.
À réception de `STALL`, le demandeur peut faire une seule relance corrélée et
bornée ; il ne sonde jamais sur minuteur. Toute instruction vers un autre agent
passe par `send.sh`, jamais par une saisie directe dans son pane tmux.
Pour une commande directe `FROM=cli`, répondre dans le TUI et ne jamais tenter
`send.sh cli`, `done.sh cli` ou un `XADD` de contournement.

Le rapport DOIT contenir:
- ✅ Status: SUCCESS / FAILED / PARTIAL
- ✅ Fichiers créés (liste complète avec chemins)
- ✅ Stats (nombre de pages, taille, durée)
- ✅ Durées par action et durée totale dans chaque compte rendu
- ✅ Temps d'exécution et attente externe séparés ; `NON MESURÉ` si nécessaire
- ✅ Erreurs rencontrées (si applicable)
- ✅ Prochaine action recommandée

**Exemple correct :** exécuter `done.sh` avec `TASK_ID`, `CYCLE`,
`CORRELATION_ID`, artefact et hash. L'identité vient de l'enveloppe ; ne jamais
écrire `FROM:` dans le texte.

**Exemple de rapport INCORRECT:**
```
FROM:300|DONE
```
(ancien terminal textuel, non corrélé et sans preuve)

### Triangle : aucun arrêt silencieux

Dans un triangle `NNN`, chaque agent `NNN-YZZ`, sauf le coordinateur
`NNN-1ZZ`, exécute `scripts/report-master.sh` après chaque travail réel et
après un prompt utilisateur direct. Le rapport est obligatoire pour
`SUCCESS`, `PARTIAL`, `FAILED`, `BLOCKED` et `INFO_REQUIRED`. Il ne remplace
jamais le terminal corrélé dû au demandeur initial et ne constitue jamais un
`DONE` ou un `SCORE` supplémentaire. Un événement de contrôle, un terminal
reçu, un doublon ou un rapport de supervision n'ouvre aucune nouvelle
obligation et ne reçoit aucun rapport en retour.
Un rapport contient uniquement le delta métier depuis le précédent. Si aucun
résultat, erreur, changement d'état ou décision requise n'est nouveau, aucun
rapport n'est émis.

## 3. GESTION DES ERREURS

1. **Erreur temporaire** (timeout, rate limit): Retry 3x avec backoff
2. **Erreur permanente** (fichier manquant, permission): Rapport immédiat à 100
3. **Blocage** (besoin input humain): Rapport à 100 avec `BLOCKED: raison`

Il n'existe aucun timeout de complétion d'un autre agent : Redis conserve le
message jusqu'à consommation. Un seuil de stagnation technique peut produire un
diagnostic, mais jamais acquitter, abandonner, redéclencher ou faire croire que
la tâche est terminée. Masters et Workers ne stoppent ni ne redémarrent leurs
pairs ; ils signalent le blocage à l'opérateur ou à 000.
Trois répétitions de la même erreur de consommation, ou un Worker `DELIVERED`
non reflété par le Master, constituent un `FRAMEWORK_BLOCKER` : émettre un
unique `BLOCKED` corrélé via `done.sh` vers `000` (détail préfixé
`FRAMEWORK_BLOCKER:`), suspendre les nouveaux dispatchs dépendants du canal et
préserver les résultats déjà livrés.

## 4. FORMAT DES MESSAGES INTER-AGENTS

```
FROM:{AGENT_ID}|{TYPE} {ENTREPRISE} - {DETAILS}
```

Types:
- `DONE` - Tâche terminée avec succès
- `FAILED` - Échec après retries
- `BLOCKED` - Besoin intervention
- `PROGRESS` - Événement métier intermédiaire réel (jalon atteint, résultat
  partiel utile, changement d'état ou blocage nouvellement constaté)

## 5. STRUCTURE DES LIVRABLES

Chaque agent crée ses fichiers dans:
```
studies/{ENTREPRISE}/{AGENT_ID}/
```

Et documente dans un fichier `_manifest.json`:
```json
{
  "agent": 300,
  "entreprise": "example.com",
  "status": "complete",
  "files": ["html/abc123.html", "..."],
  "stats": {"pages": 479, "size_mb": 125},
  "completed_at": "2024-01-30T22:30:00Z"
}
```

## 6. CHAÎNE DE RESPONSABILITÉ

```
100 (Master) dispatch → 3XX execute → rapport à 100 → 100 dispatch suivant
```

Le Master 100:
- Reçoit les rapports de TOUS les agents
- Décide de la prochaine étape
- Dispatch au prochain agent
- Track la progression globale

## 7. JAMAIS D'INTERRUPTION

Si un agent doit faire une tâche longue (crawl, analyse):
1. L'exécuter au premier plan, dans le tour de travail courant
2. Envoyer `PROGRESS` uniquement lors d'un événement métier réel, jamais sur
   minuteur et jamais via un wakeup
3. Un délai métier interne peut être légitime (healthcheck après redémarrage,
   backoff réseau borné). Il ne doit jamais servir à surveiller un autre agent.
4. Envoyer `DONE` quand terminé
5. NE JAMAIS demander confirmation pour continuer

### Interdiction des exécutions en arrière-plan non bornées

- **INTERDIT** de lancer un processus en arrière-plan (`&`, `nohup`, `setsid`,
  session ou pane tmux ad hoc, `run_in_background`), sauf exécution ponctuelle
  dont la fin autonome et rapide est certaine — typiquement des tests unitaires
  bornés.
- **INTERDIT** de lancer un script à boucle infinie (`while true`, `watch`,
  polling, daemon ad hoc), en avant-plan comme en arrière-plan. Les seuls
  processus persistants autorisés sont ceux démarrés par les scripts canoniques
  du framework (`infra.sh`, `agent.sh`, `web.sh`, `proxy.sh`).
- Avant tout lancement en arrière-plan, l'agent doit savoir que l'exécution se
  termine seule et rapidement ; dans le doute, exécuter au premier plan.

## 8. INTERDICTION DU /loop wakeup en mode IDLE

Quand tu es IDLE (aucune tache en cours, aucun dispatch en attente) :

- NE JAMAIS utiliser `ScheduleWakeup`, `/loop`, ou tout mecanisme de self-trigger pour te reveiller periodiquement.
- NE JAMAIS produire des messages "Claude resuming /loop wakeup ...".
- NE JAMAIS poller ton inbox Redis en boucle pour verifier les messages.
- TU NE FAIS RIEN tant qu'un message externe (user, hub, autre agent) n'arrive pas dans ton inbox.

Le pipeline est **event-driven** : un nouveau message dans inbox declenche
ton activation via le bridge agent.py. Pas de polling. Pas de wakeup.

**Pourquoi :** les wakeups inutiles polluent les conversations, brulent du
token, et masquent les vrais messages. Un agent IDLE doit etre SILENCIEUX.

**Exception :** si ton `system.md` decrit explicitement un cycle a duree
fixe (ex: heartbeat health-check), respecte-le. Sinon, IDLE = silence total.

## 9. INTERDICTION DES MESSAGES A SOI-MEME

**INTERDIT** : envoyer un message (send.sh, Redis XADD) a ton propre ID.

- Un agent ne s'auto-dispatch JAMAIS.
- Un agent ne s'envoie JAMAIS de signal DONE/SCORE a lui-meme.
- Si tu dois boucler, c'est ta logique interne — pas un message Redis.

## 10. CONTRAT VERIFY (V3)

**La complétion se prouve, ne se déclare pas.**

Si ta tâche porte un `verify` (champ `verify_cmd` sur le message) :

- Tu n'as **PAS** fini tant que le verify n'est pas vert. Le bridge exécute
  la commande de vérification à la fin de ta réponse ; tant qu'elle échoue,
  la tâche n'est pas terminée.
- Un message `FROM:verify|FAIL` contient l'erreur **exacte** du harnais :
  lis-la, répare la cause, ne reformule pas ta réponse précédente.
- Le signal DONE/SCORE que tu émets via `done.sh` est **consultatif** ;
  la preuve, c'est le verify (`origin=verify` dans le stream de complétion).

**Interdits absolus** (détectés par les règles anti-hacking, tâche bloquée) :

- Modifier les tests d'acceptation (`pool-requests/tests/`, `bench/oracle/`,
  `spec/acceptance/`) — en écriture comme en création de fichier.
- Ajouter des marqueurs `skip`/`xfail` pour esquiver un test rouge.
- Supprimer des assertions pour faire passer le harnais.
- Coder en dur une sortie attendue au lieu d'implémenter le comportement.

Si le verify reste rouge après épuisement du budget de tentatives, le bridge
publie `[VERIFY_FAILED] BLOCKED|task=...|raison=...` — c'est l'escalade
normale (règle 3), pas un échec de ta part à masquer.
