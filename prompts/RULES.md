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
- Déduire les métadonnées manquantes lorsqu'elles ne créent aucune ambiguïté.
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
./scripts/done.sh 100 DONE "{ENTREPRISE} - {RÉSUMÉ COMPLET}"

# Score : ./scripts/done.sh 100 SCORE 85 "{détails}"
```

**IMPORTANT :** le bridge ne lit PLUS les signaux DONE/SCORE dans le texte
de tes réponses. Écrire "DONE" dans ta réponse ne déclenche RIEN.
Seule l'EXÉCUTION de `done.sh` ou `send.sh` émet le signal inter-agent.
Pour une commande directe `FROM=cli`, répondre dans le TUI et ne jamais tenter
`send.sh cli`, `done.sh cli` ou un `XADD` de contournement.

Le rapport DOIT contenir:
- ✅ Status: SUCCESS / FAILED / PARTIAL
- ✅ Fichiers créés (liste complète avec chemins)
- ✅ Stats (nombre de pages, taille, durée)
- ✅ Erreurs rencontrées (si applicable)
- ✅ Prochaine action recommandée

**Exemple de rapport CORRECT:**
```
FROM:300|DONE example.com - SUCCESS
Crawl terminé: 479 pages HTML
Fichiers: studies/example.com/300/html/*.html (479 fichiers, 125MB)
Durée: 2h15m
Erreurs: 3 timeouts (retry OK)
Prochaine étape: Agent 306 peut extraire
```

**Exemple de rapport INCORRECT:**
```
FROM:300|Crawl en cours...
```
(Pas assez d'info pour que 100 décide)

## 3. GESTION DES ERREURS

1. **Erreur temporaire** (timeout, rate limit): Retry 3x avec backoff
2. **Erreur permanente** (fichier manquant, permission): Rapport immédiat à 100
3. **Blocage** (besoin input humain): Rapport à 100 avec `BLOCKED: raison`

Il n'existe aucun timeout de complétion d'un autre agent : Redis conserve le
message jusqu'à consommation. Un seuil de stagnation technique peut produire un
diagnostic, mais jamais acquitter, abandonner, redéclencher ou faire croire que
la tâche est terminée. Masters et Workers ne stoppent ni ne redémarrent leurs
pairs ; ils signalent le blocage à l'opérateur ou à 000.

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
1. Lancer en background si possible
2. Envoyer `PROGRESS` uniquement lors d'un événement métier réel, jamais sur
   minuteur et jamais via un wakeup
3. Un délai métier interne peut être légitime (healthcheck après redémarrage,
   backoff réseau borné). Il ne doit jamais servir à surveiller un autre agent.
4. Envoyer `DONE` quand terminé
5. NE JAMAIS demander confirmation pour continuer

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
