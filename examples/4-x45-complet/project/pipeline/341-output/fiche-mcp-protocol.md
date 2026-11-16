# Fiche analyse : Protocole MCP Tool

## Schema tool
```json
{
  "name": "string",
  "description": "string",
  "inputSchema": {
    "type": "object",
    "properties": {},
    "required": []
  }
}
```

## SDK Python
- Server("name")
- @app.list_tools() → list[Tool]
- @app.call_tool() → list[TextContent]

## Conventions
- Noms : snake_case, verb_noun
- Erreurs : retourner TextContent avec message d'erreur
- Transport : stdio

## Sources
- mcp-01 : clean/mcp-spec.md#ToolSchema
- mcp-02 : clean/mcp-spec.md#ServerSDK
- mcp-03 : clean/mcp-spec.md#Conventions
