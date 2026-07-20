# Fonctionnement des agents — mono, x45 et z21

Ce document décrit la topologie v3.2.0 et la valeur produite par chaque rôle.
Tous les agents composés utilisent un triplet `system.md`, `memory.md`,
`methodology.md` chargé par `prompts/AGENT.md`.

La pondération commune entre résultat et processus est définie dans
[Concevoir des agents orientés résultat](PROMPT_RESULT_PRIORITY.md).

## Règles communes

- Le mandat explicite récent de l'utilisateur prime sur une mémoire historique.
- `system.md` définit le contrat et le rôle par défaut.
- `memory.md` contient le contexte courant ; ce n'est pas une whitelist.
- `methodology.md` décrit la méthode réutilisable.
- Un agent ne signe jamais au nom d'un autre agent.
- Après un dispatch, l'agent rend la main. La reprise vient d'un événement du
  bridge, jamais d'une boucle de polling.
- Une tâche portant `verify_cmd` n'avance que sur la preuve du bridge.

## Mono v3.2 : deux agents

Un mono n'est plus un agent isolé. Il comprend un principal `3XX-1XX` et son
Contradictor `3XX-2XX`.

```text
Utilisateur
    │
    ▼
3XX-1XX Principal ─── résultat métier
    ▲
    │ conclusion consultative
3XX-2XX Contradictor
```

### Principal `3XX-1XX`

Le principal reçoit la demande, réalise le travail et vérifie le résultat. Il
possède le rôle fonctionnel de l'ancien mono : création, développement,
compression, administration ou autre mission définie par son contrat.

Il produit la valeur métier. Il n'attend pas le Contradictor pour travailler et
ne considère jamais le silence du `2XX` comme un blocage.

### Contradictor `3XX-2XX`

Le Contradictor analyse exclusivement le principal `3XX-1XX`. Il vérifie si la
demande a été correctement comprise, décidée, exécutée et satisfaite. Son avis
est consultatif : il ne termine pas la tâche et ne pilote pas le principal.

Voir [Contradictor 2XX](CONTRADICTOR.md) pour ses deux actions.

## x45 v3.2 : sept agents

```text
                    1XX Master
                         ▲
                         │ conclusion
                    2XX Contradictor

7XX Curator → 3XX Developer → 5XX Observer → 8XX Coach
                    ▲                              │
                    └──── candidate méthodologique┘
                         9XX Architect
```

### `1XX` — Master

Le Master choisit la tâche active, matérialise le cycle déclaratif et dispatch
chaque étape. Il conserve `TASK`, `CYCLE` et `CORR`, vérifie les artefacts et
rend la main après chaque dispatch. Il orchestre ; il ne remplace pas le
Developer.

Il reste propriétaire du résultat jusqu'à la Phase C réellement exécutée, aux
tests dans la destination et au passage de la tâche à DONE. Il décide depuis le
verdict de l'Observer, jamais depuis le score qualitatif seul.

### `2XX` — Contradictor du Master

Le Contradictor examine le comportement du `1XX`, hors du cycle métier. Il
cherche le premier écart dans la chaîne demande → compréhension → décision →
action → résultat. Il peut discuter son analyse avec l'utilisateur, puis envoyer
une conclusion autonome au Master. Son message ne fait avancer aucune
transition.

### `3XX` — Developer

Le Developer produit le livrable. Il consomme le contexte borné du Curator,
applique sa méthodologie, exécute les vérifications et publie un artefact
traçable. Son `DONE` reste consultatif lorsqu'un `verify_cmd` est défini.

### `5XX` — Observer

L'Observer évalue le résultat du Developer dans le cycle. Il sépare les hard
gates du score qualitatif et produit `ECHEC`, `PREUVE`, `CAUSE_PROBABLE` et
`CONTRE_EXEMPLE`. Contrairement au `2XX`, il juge le livrable du `3XX`, pas la
compréhension et l'orchestration du Master.

Il sépare `DEV_BLOCKERS`, `INTEGRATION_ACTIONS` et `OPTIONAL_IMPROVEMENTS`, puis
rend `BLOCK_DEV`, `READY_FOR_INTEGRATION`, `BLOCK_INTEGRATION` ou
`ACCEPT_WITH_IMPROVEMENTS`. Des hard gates verts avec seulement des améliorations
facultatives imposent la livraison, même si le score est inférieur à 98.

### `7XX` — Curator

Le Curator prépare une `memory.md` bornée et vérifiable pour le Developer. Il
sélectionne le contexte utile sans inventer de faits ni transformer une ancienne
liste de fichiers en limite permanente.

### `8XX` — Coach

Le Coach exploite les bilans du `5XX` pour proposer une amélioration de méthode.
Il écrit une candidate par delta et ne remplace jamais directement la
méthodologie active. La promotion exige le gate de non-régression.
Cette amélioration vise le prochain cycle et ne bloque pas la Phase C courante.

## Décision canonique de fin de cycle

```text
Developer → Observer
              ├─ BLOCK_DEV → Developer
              ├─ READY_FOR_INTEGRATION → Master Phase C → DONE
              ├─ BLOCK_INTEGRATION → Master corrige Phase C → DONE
              └─ ACCEPT_WITH_IMPROVEMENTS → Phase C → DONE
                                             └→ Coach (non bloquant)
```

Les critères obligatoires et hard gates gouvernent la livraison. Le score mou
sert au diagnostic et au coaching ; `score < 98` n'est jamais une transition.

### `9XX` — Architect

L'Architect garantit la cohérence du triangle, de ses contrats et de sa
topologie. Il arbitre les changements structurels et les contrats durables. Il
ne doit pas devenir un passage obligatoire pour une correction projet ordinaire.

## z21 v3.2 : sept agents et contextes interchangeables

z21 possède les mêmes sept classes de rôle que x45. Sa différence est le
contexte : le Master sélectionne un sous-contexte fonctionnel, puis tous les
agents du cycle travaillent avec ce même contexte.

```text
demande → 1XX sélectionne le contexte → 7XX le borne → 3XX réalise
                                                   │
                                      5XX évalue → 8XX améliore

2XX analyse le 1XX hors cycle              9XX maintient les contextes
```

### `1XX` — Master routeur

Il identifie le domaine concerné, choisit le sous-contexte et transmet la tâche
avec une enveloppe corrélée. Il évite de charger tout le gros système quand un
contexte précis suffit.

### `2XX` — Contradictor du routeur

Il analyse notamment les erreurs de routage : mauvais contexte, contexte trop
large ou trop pauvre, instruction déformée, dispatch incohérent, attente
impossible ou résultat sans rapport avec la demande. Ses actions restent
`analyse` et `envoie`.

### `3XX` — Developer

Il charge le sous-contexte indiqué, réalise la modification et vérifie le
résultat sans étendre inutilement son périmètre.

### `5XX` — Observer

Il exécute les hard gates et l'évaluation adaptés au sous-contexte. Il produit
un bilan vérifiable destiné au Master et au Coach.

### `7XX` — Curator

Il transforme le sous-contexte sélectionné en mémoire de travail minimale,
actuelle et vérifiable pour le Developer.

### `8XX` — Coach

Il propose les améliorations méthodologiques propres au sous-contexte, sans
écraser directement la méthode active.

### `9XX` — Architect

Il crée, fusionne, découpe et maintient les sous-contextes. Il garantit leur
cohérence globale et évite les doublons ou les zones sans propriétaire.

## Différence entre `2XX` et `5XX`

| Question | `2XX` Contradictor | `5XX` Observer |
|---|---|---|
| Cible | `1XX` | résultat du `3XX` |
| Position | hors cycle | dans le cycle |
| Valeur | cohérence de compréhension et d'orchestration | qualité du livrable |
| Déclenchement | utilisateur : `analyse`, puis éventuellement `envoie` | workflow du Master |
| Sortie | conclusion consultative au `1XX` | bilan, hard gates et score |
| Effet direct sur le cycle | aucun | transition selon la preuve du bridge |

## Affectation par défaut

| Rôles | Login | Effort |
|---|---|---|
| Developer ou principal mono | `login1a` | `H` |
| Observer + Coach | `login2a` | `H` |
| Master + Contradictor | `login3a` | `H` |
| Curator + Architect | `login4a` | `H` |

Tous les profils utilisent le slot `a` par défaut.
