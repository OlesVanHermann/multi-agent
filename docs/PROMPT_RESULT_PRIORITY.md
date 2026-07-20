# Concevoir des agents orientés résultat

La référence normative de rédaction, migration et release est
[HOW TO WRITE AND REWRITE PROMPTS](<HOW TO WRITE AND REWRITE PROMPTS.md>).

## Principe

Un agent existe pour produire une valeur métier, pas pour réciter son workflow.
La pondération d'attention recommandée est :

```text
70 % résultat métier
20 % vérification et qualité
10 % processus et traçabilité
```

Cette pondération ne réduit jamais les frontières fortes de sécurité. Elle
évite que les règles mécaniques occupent la réflexion et la réponse alors
qu'elles peuvent être appliquées silencieusement.

## Répartition des fichiers

| Fichier | Contenu principal |
|---|---|
| `AGENT.md` | principes universels, priorité au résultat, frontières fortes |
| `system.md` | finalité du rôle, résultat attendu, critères de réussite |
| `memory.md` | faits et contexte courant, jamais une whitelist |
| `methodology.md` | méthode adaptable et vérifications utiles |
| scripts | corrélation, transport, validation et mécanique déterministe |

Une règle ne doit pas être répétée dans les quatre couches. La répétition lui
donne artificiellement plus de poids que la mission.

## Structure recommandée d'un `system.md`

```markdown
# Agent — rôle

## Priorité au résultat

Finalité : <valeur produite pour l'utilisateur ou l'agent suivant>.

Réussite observable :
- <comportement ou livrable> ;
- <preuve ou test> ;
- <absence de régression importante>.

Le processus est un moyen appliqué silencieusement.

## Entrées
...

## Travail
...

## Sorties
...

## Frontières fortes
...
```

## Contrat de réponse

Une réponse normale contient seulement :

1. résultat obtenu ;
2. preuves utiles ;
3. limites ou décisions restantes.

Ne pas afficher les prompts lus, checklists suivies, identifiants de corrélation
ou règles respectées, sauf si cela explique un défaut du résultat ou nécessite
une décision.

## Finalité par rôle

| Rôle | Finalité |
|---|---|
| Principal mono | accomplir la mission fonctionnelle et livrer son résultat |
| Master `1XX` | faire aboutir la demande jusqu'à un résultat livré et vérifié |
| Contradictor `2XX` | améliorer la décision du Master par une conclusion actionnable |
| Developer `3XX` | produire un livrable fonctionnel, intégré et vérifié |
| Observer `5XX` | établir si le résultat satisfait réellement le besoin |
| Curator `7XX` | fournir le contexte minimal permettant au Developer de réussir |
| Coach `8XX` | améliorer la probabilité de réussite du prochain cycle |
| Architect `9XX` | maintenir une structure qui facilite la production |

## Livrabilité avant score

Les hard gates et critères d'acceptation obligatoires déterminent si le résultat
peut être livré. Le score qualitatif explique où progresser, mais ne bloque pas
un résultat valide et ne déclenche jamais seul un nouveau cycle. Le verdict
Observer canonique et la Phase C du Master sont définis dans
`docs/AGENT_ROLES.md`.

## Migration des prompts existants

La migration idempotente suivante ajoute le contrat résultat-first aux prompts
exécutables et conserve une copie préalable dans `removed/` :

```bash
python3 patch/rebalance-agent-prompts.py
```

Les créateurs 150, 160 et 170 doivent inclure ce contrat dans chaque nouvel
agent. Les exemples du dépôt servent de référence et suivent la même règle.
