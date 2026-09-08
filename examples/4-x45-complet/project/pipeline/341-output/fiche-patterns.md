# Fiche analyse : Patterns serveur MCP

## Pattern identifié
1. Créer Server("nom")
2. Décorer @app.list_tools()
3. Décorer @app.call_tool() avec match/case
4. stdio_server() context manager
5. asyncio.run(main())

## Gestion d'erreurs
- Validation dans call_tool
- Erreurs douces via TextContent
- Pas d'exception propagée au client

## Sources
- ex-01 : clean/example-server.md#Pattern
- ex-02 : clean/example-server.md#ErrorHandling
