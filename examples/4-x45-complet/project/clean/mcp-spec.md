# MCP — Tool Definition

## Schema d'un tool

```json
{
  "name": "tool_name",
  "description": "What the tool does",
  "inputSchema": {
    "type": "object",
    "properties": {
      "param1": { "type": "string", "description": "..." }
    },
    "required": ["param1"]
  }
}
```

## Server Python SDK

```python
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

app = Server("server-name")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [Tool(name=..., description=..., inputSchema=...)]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    return [TextContent(type="text", text="result")]

async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
```

## Conventions
- Noms : snake_case, verb_noun
- Erreurs : TextContent avec message, pas d'exception
- Transport : stdio (standard)
