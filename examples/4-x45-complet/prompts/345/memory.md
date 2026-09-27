# 345 — Memory (cycle 5)
Curé par 745.

## Tâche
Écrire le code Python final du serveur MCP

## Spec 342 (cycle 5)
- Fonction : set_cell_background_color(sheet_name: str, cell_address: str, color: str) -> str
- Normalisation : cell_address.upper().strip()
- Validation : regex compilées
- Appels UNO SYNCHRONES → asyncio.to_thread() chaque appel séparément
- Reconnexion auto si connexion UNO périmée (test liveness avant chaque appel)
- CellBackColor = -1 → "none"
- Graceful shutdown : SIGTERM → log + cleanup

## Imports
mcp.server, mcp.types, mcp.server.stdio, uno, asyncio, re, os, logging, signal
com.sun.star.container.NoSuchElementException
com.sun.star.lang.IllegalArgumentException
typing.Any
