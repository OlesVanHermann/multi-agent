# 345 — Methodology (cycle 5)

## Structure du code
```python
# 1. Imports
# 2. Logging setup
# 3. Constantes (regex, ports)
# 4. Classe UnoConnection (cache + reconnexion auto)
# 5. Helpers avec type hints + docstrings
# 6. Server MCP
# 7. @list_tools → list[Tool]
# 8. @call_tool → match/case dispatch
# 9. Fonctions tool avec try/except SPÉCIFIQUES
# 10. main() avec graceful shutdown + asyncio.run
```

## Constantes obligatoires
```python
UNO_PORT = int(os.environ.get("UNO_PORT", "2002"))
RE_CELL_ADDRESS = re.compile(r"^[A-Z]+[0-9]+$")
RE_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
```

## Logging, async/to_thread, validation
(inchangé depuis cycle 4)

## Reconnexion automatique (cycle 5)
```python
class UnoConnection:
    def __init__(self, port: int = UNO_PORT):
        self._port = port
        self._desktop: Any = None

    def get_desktop(self) -> Any:
        try:
            if self._desktop is not None:
                self._desktop.getCurrentComponent()  # test liveness
                return self._desktop
        except Exception:
            logger.warning("UNO connection stale, reconnecting")
            self._desktop = None
        self._desktop = connect_uno(self._port)
        return self._desktop
```
**Tester la connexion avant chaque utilisation. Reconnecter si périmée.**

## Graceful shutdown (cycle 5)
```python
async def main() -> None:
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: ...)
```
Intercepter SIGTERM pour log propre.

## Appels UNO séparés (cycle 5)
Chaque appel UNO = un to_thread séparé :
```python
sheets = await asyncio.to_thread(doc.getSheets)
sheet = await asyncio.to_thread(sheets.getByName, sheet_name)
```
PAS : `await asyncio.to_thread(doc.getSheets().getByName, name)` (2 appels chaînés)

## Changelog
- cycle 2 : type hints, docstrings, try/except, match/case, validation
- cycle 3 : exceptions spécifiques, constantes, port configurable
- cycle 4 : logging, asyncio.to_thread(), connection reuse
- cycle 5 : reconnexion auto (UnoConnection), graceful shutdown, appels UNO séparés
  Raison : bilan 500 cycle 5, P1+P2+P3

## Timeout UNO (cycle 6)
Wrapper optionnel pour les appels UNO longs :
```python
await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=10.0)
```
Timeout de 10s par défaut. Configurable via UNO_TIMEOUT env var.

## Module exports (cycle 6)
```python
__all__ = ["app", "main"]
```

## Changelog addendum
- cycle 6 (845) : timeout UNO optionnel, __all__, description case-insensitive
  Raison : bilan 500 cycle 6, P1+P2+P3 (tous mineurs/cosmétiques)
  NOTE : pipeline stabilisé, boucle courte terminée
