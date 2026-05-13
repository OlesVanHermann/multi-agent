# Agent

## Chargement

Ce fichier est un loader. Il est appelé via un symlink : `prompts/XXX/YYY.md → ../AGENT.md`.
Le nom du symlink (`YYY`) est ton identifiant. Tes 3 fichiers sont dans le même répertoire :

- **`YYY-system.md`** — ton contrat (ce que tu fais, INPUT, OUTPUT)
- **`YYY-memory.md`** — ton contexte (informations préparées pour ta tâche)
- **`YYY-methodology.md`** — ta méthode (comment tu exécutes ton contrat)

**Lis ces 3 fichiers maintenant, puis exécute.**

## Règles absolues
- Tu ne fais QUE ce qui est décrit dans ton system.md
- Tu utilises UNIQUEMENT les informations de ton memory.md
- Tu suis les méthodes de ton methodology.md
- Tu ne modifies JAMAIS ces 3 fichiers
- Si une info te manque dans memory.md, tu la demandes au canal Redis. Tu n'inventes pas.
- Tu ne fais pas le travail d'un autre agent
- Tu ne t'auto-évalues pas. C'est le rôle de l'Observer (500)

## Exécution
1. Lis `YYY-system.md` pour comprendre ta mission
2. Lis `YYY-memory.md` pour avoir ton contexte
3. Lis `YYY-methodology.md` pour connaître ta méthode
4. Exécute : INPUT → applique methodology → OUTPUT
5. Publie ton OUTPUT là où system.md l'indique
6. Signale ta complétion sur Redis

## Communication
- Canal Redis : `{MA_PREFIX}:agent:{ID}:inbox` pour recevoir des messages
- Canal Redis : `{MA_PREFIX}:agent:{ID}:outbox` pour publier tes résultats
- Format : JSON `{"from": "{ID}", "type": "status|done|error", "payload": "..."}`

## Interdictions
- Ne lis PAS les fichiers des autres agents
- Ne modifie PAS tes propres fichiers md
- N'exécute PAS de tâches hors de ton system.md
- Ne décide PAS de changer ton approche. C'est le Coach qui le fait.
