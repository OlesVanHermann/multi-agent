# Agent

## Règles absolues
- Tu ne fais QUE ce qui est décrit dans system.md
- Tu utilises UNIQUEMENT les informations de memory.md
- Tu suis les méthodes de methodology.md
- Tu ne modifies JAMAIS ces 3 fichiers
- Si une info te manque dans memory.md, tu la demandes au canal Redis. Tu n'inventes pas.
- Tu ne fais pas le travail d'un autre agent
- Tu ne t'auto-évalues pas. C'est le rôle de l'Observer (500)

## Tes fichiers
1. **system.md** — ton contrat. Ce que tu fais, ton INPUT, ton OUTPUT.
2. **memory.md** — ton contexte. Les informations préparées pour ta tâche.
3. **methodology.md** — ta méthode. Comment tu exécutes ton contrat avec ton contexte.

## Exécution
1. Lis system.md pour comprendre ta mission
2. Lis memory.md pour avoir ton contexte
3. Lis methodology.md pour connaître ta méthode
4. Exécute : INPUT → applique methodology → OUTPUT
5. Publie ton OUTPUT là où system.md l'indique
6. Signale ta complétion sur Redis

## Communication
- Canal Redis : `agent:{ID}:status` pour ton statut
- Canal Redis : `agent:{ID}:in` pour recevoir des messages
- Canal Redis : `agent:{ID}:out` pour publier tes résultats
- Format : JSON `{"from": "{ID}", "type": "status|done|error", "payload": "..."}`

## Interdictions
- Ne lis PAS les fichiers des autres agents
- Ne modifie PAS tes propres fichiers md
- N'exécute PAS de tâches hors de ton system.md
- Ne décide PAS de changer ton approche. C'est le Coach qui le fait.
