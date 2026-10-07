# 342 — Memory (cycle 4)
Curé par 742.

## Tâche en cours
Produire la spec technique pour set_cell_background_color

## Fiches d'analyse de 341 (résumé cycle 4)
- UNO API : CellBackColor (int), getByName, getCellRangeByName
  - Tous les appels sont SYNCHRONES
  - CellBackColor = -1 signifie "aucune couleur définie"
- MCP : Server, Tool, TextContent, stdio_server
- Pattern : match/case dispatch, async handlers

## Contraintes spéciales
- Appels UNO bloquants dans contexte async → documenter
- Normalisation d'entrée nécessaire (cell_address case-insensitive)
