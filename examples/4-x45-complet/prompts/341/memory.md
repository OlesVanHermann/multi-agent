# 341 — Memory (cycle 1)
Curé par 741. Chunks: uno-01, uno-02, uno-03, uno-04, uno-05, mcp-01, mcp-02, mcp-03, ex-01, ex-02

## Tâche en cours
Analyser les APIs nécessaires pour implémenter set_cell_background_color

## Données UNO
- CellBackColor : long (int32), couleur RGB de fond. -1 = transparent
- IsCellBackgroundTransparent : boolean
- Accès cellule : getCellByPosition(col, row) ou getCellRangeByName("A1")
- Conversion : hex→int via int("FF0000",16), int→RGB via shift
- Connexion : UnoUrlResolver, socket localhost:2002, Desktop

## Données MCP
- Tool schema : name, description, inputSchema (object, properties, required)
- Server SDK : Server(), @list_tools, @call_tool, stdio_server()
- Conventions : snake_case, verb_noun, erreurs via TextContent

## Pattern serveur
- Server("name") → @list_tools → @call_tool match/case → stdio_server → asyncio.run
- Erreurs soft (TextContent), pas d'exception
