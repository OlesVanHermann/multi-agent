# Exemple : filesystem-server

## Pattern identifié

```
1. Server("name")
2. @app.list_tools() → list[Tool]
3. @app.call_tool() → match/case dispatch → list[TextContent]
4. stdio_server() context manager
5. asyncio.run(main())
```

## Code de référence

```python
@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    match name:
        case "read_file":
            path = Path(arguments["path"])
            if not path.exists():
                return [TextContent(type="text", text=f"Error: not found: {path}")]
            return [TextContent(type="text", text=path.read_text())]
        case _:
            return [TextContent(type="text", text=f"Error: unknown tool {name}")]
```

## Points clés
- Validation input dans call_tool (pas dans list_tools)
- Erreurs soft via TextContent (pas d'exception)
- match/case pour le dispatch
- Path.parent.mkdir(parents=True) pour la sécurité
