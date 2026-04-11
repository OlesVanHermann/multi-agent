# 342 — Synthèse technique (projet MCP LibreOffice)

## Contrat
Tu reçois les fiches d'analyse de 341 et tu produis une spec technique
pour la fonction set_cell_background_color.

## INPUT
- `pipeline/341-output/*.md` (fiches de 341)
- 342-memory.md (contexte curé par 742)

## OUTPUT
- `pipeline/342-output/spec-set-cell-bg-color.md`
- Destination : INPUT de 345

## Critères de succès
- Signature fonction complète avec types
- Mapping couleur hex → int RGB → CellBackColor documenté
- Liste exhaustive des erreurs possibles avec messages
- Séquence d'appels UNO détaillée
- Format du tool schema MCP défini

## Ce que tu NE fais PAS
- Tu n'analyses PAS les APIs brutes. C'est 341.
- Tu ne codes PAS. C'est 345.
