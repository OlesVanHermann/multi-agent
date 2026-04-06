# 342 — Methodology (cycle 4)

## Signature
- ALWAYS type hints Python dans la signature
- ALWAYS documenter le return type
- Pour chaque param string : regex de validation

## Spec obligatoire
- Section Préconditions
- Section Séquence avec types retour
- Section Erreurs : Condition, Exception, Message, Handling

## Ajouts cycle 4 (842)
- ALWAYS documenter la normalisation d'entrée (cell_address → .upper().strip())
- ALWAYS préciser sync/async et implications event loop
- ALWAYS documenter valeurs spéciales (CellBackColor -1)
- Si appel bloquant en contexte async → mentionner asyncio.to_thread()

## Changelog
- cycle 2 (842) : type hints, regex, return type
- cycle 3 (842) : préconditions, types retour séquence
- cycle 4 (842) : normalisation, sync/async, valeurs spéciales
