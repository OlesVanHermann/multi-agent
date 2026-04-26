# 161-361 Methodology — Ecriture de specs

## Mode STANDARD (cycle 1)
1. Lire memory.md (contexte vendor + code existant)
2. Identifier les endpoints necessaires
3. Definir les models Pydantic
4. Definir les composants frontend
5. Ecrire les tests attendus
6. Lister les criteres d'acceptation
7. Ecrire CHANGES.md complet

## Mode CORRECTION (cycle 2+)
1. Lire bilans/161-cycle{N-1}.md pour les criteres faibles
2. Corriger uniquement les sections signalees
3. Ne PAS reecrire les sections qui scorent bien

## Patterns de bons specs (exemples)
- Endpoint table : toujours Method | Path | Description
- Model : nom + champs principaux + types
- Hook : nom + return type + params
- Test : "18 tests couvrant create, delete, share, system protection"
- Critere : formule testable, pas vague ("l'utilisateur peut X" pas "UX ok")
