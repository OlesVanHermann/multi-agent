"""MCP Server for LibreOffice Calc.

Provides tools to manipulate LibreOffice Calc spreadsheets
via the UNO bridge and the Model Context Protocol.

Usage:
    UNO_PORT=2002 python mcp_libreoffice_calc.py
"""

import asyncio
import logging
import os
import re
import signal
from typing import Any

import uno
from com.sun.star.container import NoSuchElementException
from com.sun.star.lang import IllegalArgumentException

from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

__all__ = ["app", "main"]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger: logging.Logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UNO_PORT: int = int(os.environ.get("UNO_PORT", "2002"))
RE_CELL_ADDRESS: re.Pattern = re.compile(r"^[A-Z]+[0-9]+$")
RE_HEX_COLOR: re.Pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
UNO_TIMEOUT: float = float(os.environ.get("UNO_TIMEOUT", "10.0"))


# ---------------------------------------------------------------------------
# UNO connection with auto-reconnect
# ---------------------------------------------------------------------------


class UnoConnection:
    """Manages a cached UNO bridge connection with automatic reconnection.

    The connection is tested for liveness before each use. If LibreOffice
    has been restarted, the stale connection is discarded and a fresh one
    is established transparently.
    """

    def __init__(self, port: int = UNO_PORT) -> None:
        self._port: int = port
        self._desktop: Any = None

    def get_desktop(self) -> Any:
        """Return a live XDesktop, reconnecting if the cached one is stale.

        Returns:
            XDesktop instance for document access.

        Raises:
            ConnectionRefusedError: If LibreOffice is not running.
        """
        if self._desktop is not None:
            try:
                self._desktop.getCurrentComponent()  # liveness probe
                return self._desktop
            except Exception:
                logger.warning("UNO connection stale, reconnecting on port %d", self._port)
                self._desktop = None

        logger.debug("Opening UNO connection on port %d", self._port)
        local_context = uno.getComponentContext()
        resolver = local_context.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local_context
        )
        ctx = resolver.resolve(
            f"uno:socket,host=localhost,port={self._port};urp;"
            "StarOffice.ComponentContext"
        )
        smgr = ctx.ServiceManager
        self._desktop = smgr.createInstanceWithContext(
            "com.sun.star.frame.Desktop", ctx
        )
        logger.info("UNO connection established on port %d", self._port)
        return self._desktop

    def close(self) -> None:
        """Discard the cached connection."""
        self._desktop = None
        logger.debug("UNO connection closed")


_uno: UnoConnection = UnoConnection()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

app = Server("libreoffice-calc")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return the list of available tools."""
    return [
        Tool(
            name="set_cell_background_color",
            description="Set the background color of a cell in LibreOffice Calc",
            inputSchema={
                "type": "object",
                "properties": {
                    "sheet_name": {
                        "type": "string",
                        "description": "Name of the sheet (e.g. Sheet1)",
                    },
                    "cell_address": {
                        "type": "string",
                        "description": "Cell address, case-insensitive (e.g. A1, b3, aa12)",
                    },
                    "color": {
                        "type": "string",
                        "description": "Background color in hex (#RRGGBB)",
                    },
                },
                "required": ["sheet_name", "cell_address", "color"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch incoming tool calls to the appropriate handler."""
    match name:
        case "set_cell_background_color":
            return await _set_cell_background_color(arguments)
        case _:
            logger.warning("Unknown tool called: %s", name)
            return [TextContent(type="text", text=f"Error: unknown tool: {name}")]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def _set_cell_background_color(args: dict) -> list[TextContent]:
    """Set the background color of a spreadsheet cell.

    Normalizes cell_address to uppercase. All UNO calls are offloaded
    to a worker thread via asyncio.to_thread() to avoid blocking the
    event loop.

    Args:
        args: Dictionary with keys sheet_name, cell_address, color.

    Returns:
        List with confirmation message or error description.
    """
    sheet_name: str = args.get("sheet_name", "").strip()
    cell_address: str = args.get("cell_address", "").upper().strip()
    color: str = args.get("color", "").strip()

    # --- Argument validation ---
    if not sheet_name:
        logger.warning("Missing sheet_name")
        return [TextContent(type="text", text="Error: sheet_name is required")]

    if not RE_CELL_ADDRESS.match(cell_address):
        logger.warning("Invalid cell address: %s", cell_address)
        return [TextContent(
            type="text",
            text=f"Error: invalid cell address: {cell_address}. "
                 "Use format like A1, B3, AA12",
        )]

    if not RE_HEX_COLOR.match(color):
        logger.warning("Invalid color: %s", color)
        return [TextContent(
            type="text",
            text=f"Error: invalid color: {color}. Use #RRGGBB (e.g. #FF0000)",
        )]

    # --- UNO connection (async-safe, auto-reconnect) ---
    try:
        desktop = await asyncio.to_thread(_uno.get_desktop)
    except ConnectionRefusedError:
        logger.error("Cannot connect to LibreOffice on port %d", UNO_PORT)
        return [TextContent(
            type="text",
            text=f"Error: cannot connect to LibreOffice on port {UNO_PORT}. "
                 "Start with: soffice --calc --accept='socket,host=localhost,"
                 f"port={UNO_PORT};urp;'",
        )]

    # --- Document access (async-safe) ---
    doc = await asyncio.to_thread(desktop.getCurrentComponent)
    if doc is None:
        logger.error("No document open in LibreOffice")
        return [TextContent(
            type="text",
            text="Error: no document open in LibreOffice",
        )]

    # --- Sheet access (async-safe, separate calls) ---
    try:
        sheets = await asyncio.to_thread(doc.getSheets)
        sheet = await asyncio.to_thread(sheets.getByName, sheet_name)
    except NoSuchElementException:
        sheets_obj = await asyncio.to_thread(doc.getSheets)
        count: int = await asyncio.to_thread(sheets_obj.getCount)
        available: list[str] = []
        for i in range(count):
            s = await asyncio.to_thread(sheets_obj.getByIndex, i)
            available.append(s.Name)
        logger.error("Sheet not found: %s (available: %s)", sheet_name, available)
        return [TextContent(
            type="text",
            text=f"Error: sheet not found: {sheet_name}. "
                 f"Available: {', '.join(available)}",
        )]

    # --- Cell access (async-safe) ---
    try:
        cell = await asyncio.to_thread(sheet.getCellRangeByName, cell_address)
    except IllegalArgumentException:
        logger.error("Cannot access cell: %s", cell_address)
        return [TextContent(
            type="text",
            text=f"Error: cannot access cell: {cell_address}",
        )]

    # --- Color change (async-safe) ---
    old_color: int = cell.CellBackColor
    color_int: int = int(color.lstrip("#"), 16)
    await asyncio.to_thread(setattr, cell, "CellBackColor", color_int)

    old_display: str = "none" if old_color == -1 else f"#{old_color:06X}"
    logger.info(
        "Changed %s on %s from %s to %s",
        cell_address, sheet_name, old_display, color,
    )

    return [TextContent(
        type="text",
        text=f"OK: {cell_address} on {sheet_name} "
             f"changed from {old_display} to {color}",
    )]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    """Run the MCP server over stdio transport with graceful shutdown."""
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("Received shutdown signal, cleaning up")
        _uno.close()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    logger.info("Starting MCP server libreoffice-calc on UNO port %d", UNO_PORT)
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
