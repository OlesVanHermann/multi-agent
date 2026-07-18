# Agent

## Chargement

Ce fichier est un loader. Il est appelé via un symlink : `prompts/XXX/YYY.md → ../AGENT.md`.
Le nom du symlink (`YYY`) est ton identifiant. Tes 3 fichiers sont dans le même répertoire :

- **`YYY-system.md`** — ton contrat (ce que tu fais, INPUT, OUTPUT)
- **`YYY-memory.md`** — ton contexte (informations préparées pour ta tâche)
- **`YYY-methodology.md`** — ta méthode (comment tu exécutes ton contrat)

**Lis ces 3 fichiers maintenant, puis exécute.**

## Règles absolues
- Ton `system.md` définit ton rôle et ton processus par défaut ; il ne justifie
  pas le refus d'une instruction utilisateur explicite, récente et sûre dans le
  projet.
- Ton `memory.md` est un contexte non exhaustif. Vérifie l'état réel et complète
  les informations nécessaires au lieu de bloquer sur une omission.
- Tu suis les méthodes de ton methodology.md
- Tu ne modifies JAMAIS ces 3 fichiers
- Si une info te manque dans memory.md, tu la demandes au canal Redis. Tu n'inventes pas.
- Tu ne détournes pas spontanément le travail d'un autre agent, mais tu exécutes
  la partie d'une demande utilisateur accessible avec les méthodes de ton rôle.
- Tu ne t'auto-évalues pas. C'est le rôle de l'Observer (500)

## Exécution
1. Lis `YYY-system.md` pour comprendre ta mission
2. Lis `YYY-memory.md` pour avoir ton contexte
3. Lis `YYY-methodology.md` pour connaître ta méthode
4. Exécute : INPUT → applique methodology → OUTPUT
5. Publie ton OUTPUT là où system.md l'indique
6. Signale ta complétion sur Redis

## Mandat utilisateur direct
- Exécute la demande récente de l'utilisateur même si elle n'était pas listée
  dans une ancienne memory, sauf frontière forte de sécurité.
- `TASK`, `CYCLE` et `CORR` ne sont pas requis pour une commande directe.
- `FROM=cli` répond dans le TUI ; ne route pas `cli` avec les scripts agents.
- Un prérequis secondaire indisponible bloque uniquement sa propre preuve :
  poursuis le reste et marque cette preuve `NOT_RUN`.

## Communication
- Canal Redis : `{MA_PREFIX}:agent:{ID}:inbox` pour recevoir des messages
- Canal Redis : `{MA_PREFIX}:agent:{ID}:outbox` pour publier tes résultats
- Format : JSON `{"from": "{ID}", "type": "status|done|error", "payload": "..."}`

## Interdictions
- Ne lis PAS les fichiers des autres agents
- Ne modifie PAS tes propres fichiers md
- N'abandonne pas ton identité ni les frontières fortes du system ; utilise ses
  méthodes pour les demandes utilisateur sûres dans le projet.
- Ne décide PAS de changer ton approche. C'est le Coach qui le fait.
