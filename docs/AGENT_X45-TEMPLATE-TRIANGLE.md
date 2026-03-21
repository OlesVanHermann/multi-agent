# Template Triangle

## Le carré agent

```
                      ┌───────┐
                      │  9XX  │
                      └───┬───┘
                          │
                          ▼
              ┌───────────────────────┐
              │      system.md        │
              ├───────────────────────┤
 INPUT        │                       │        OUTPUT
┌──────────┐  │                       │  ┌──────────────┐
│memory.md │─►│         NXX           │─►│              │
└──────────┘  │                       │  └──────────────┘
     ▲        ├───────────────────────┤
     │        │   methodology.md      │
     │        └───────────────────────┘
     │                    ▲
     │                    │
┌────┴───┐          ┌─────┴────┐
│  7XX   │          │   8XX    │
└────────┘          └──────────┘
```

## Trois fichiers, trois propriétés

| Fichier | Mutabilité | Taille | Écrit par |
|---------|-----------|--------|-----------|
| system.md | Immutable (sauf boucle longue) | ~20-50 lignes | 9XX |
| memory.md | Curé en continu | Budget tokens strict | 7XX |
| methodology.md | Amélioré après chaque cycle | Croît puis se stabilise | 8XX |

## Deux catégories d'agents

### Agent lourd (3XX)
Triangle complet avec 7XX + 8XX + 9XX dédiés.
Memory.md curé dynamiquement. Methodology améliorée itérativement.

### Agent léger (200, 500, 600, 7XX, 8XX)
system.md par 945 ou 900. Memory.md = input direct (pas de curator dédié).
Methodology stable, maintenue par 800 global.

## Règle de récursion

Les agents de préparation (7XX, 8XX) ne nécessitent PAS leur propre triangle.
- 7XX : INPUT = index (infra 600), pas besoin de curator
- 8XX : INPUT = bilans (output 500), pas besoin de curator
- La récursion s'arrête aux agents légers

## Assemblage du prompt

L'agent runner charge dans cet ordre :
1. AGENT.md (règles universelles)
2. system.md (contrat)
3. memory.md (contexte)
4. methodology.md (méthodes)

Le tout est concaténé et envoyé comme system prompt.
