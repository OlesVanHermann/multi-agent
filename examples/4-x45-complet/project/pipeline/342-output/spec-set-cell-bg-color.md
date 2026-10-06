# Spec : set_cell_background_color

## Signature Python
```python
def set_cell_background_color(sheet_name: str, cell_address: str, color: str) -> str:
```

## Paramètres
| Param | Type | Validation | Pattern | Normalisation |
|-------|------|------------|---------|---------------|
| sheet_name | str | Non vide | `.+` | .strip() |
| cell_address | str | Lettre(s)+chiffre(s) | `^[A-Z]+[0-9]+$` | .upper().strip() |
| color | str | Hex RGB 6 digits | `^#[0-9A-Fa-f]{6}$` | (aucune) |

## Return
- Type : str
- Format : "OK: {cell} on {sheet} changed from #{old:06X} to {new}"
- Note : si old_color == -1, afficher "none" au lieu de "#FFFFFF" fallacieux

## Préconditions
- LibreOffice Calc lancé avec listener socket (port configurable, défaut 2002)
- Document tableur ouvert (getCurrentComponent() != None)
- Feuille sheet_name existe

## Séquence d'appels
1. _get_or_connect(port) → desktop: XDesktop — **SYNC, wrapper to_thread**
2. desktop.getCurrentComponent() → doc: XComponent | None — **SYNC, wrapper to_thread**
3. doc.getSheets().getByName(sheet_name) → sheet: XSpreadsheet — **SYNC, wrapper to_thread**
4. sheet.getCellRangeByName(cell_address) → cell: XCellRange — **SYNC, wrapper to_thread**
5. old_color = cell.CellBackColor → int (-1 = pas de couleur)
6. color_int = int(color.lstrip("#"), 16) → int
7. cell.CellBackColor = color_int — **SYNC, wrapper to_thread**
8. Return confirmation string

## Erreurs
| Condition | Exception | Message | Handling |
|-----------|-----------|---------|---------|
| LO non lancé | ConnectionRefusedError | "Cannot connect... Start with: soffice..." | TextContent + logger.error |
| Aucun doc ouvert | (None check) | "No document open" | TextContent + logger.error |
| Feuille inexistante | NoSuchElementException | "Sheet not found: X. Available: ..." | TextContent + logger.error |
| Adresse invalide | (regex) | "Invalid cell address: X" | TextContent + logger.warning |
| Couleur invalide | (regex) | "Invalid color: X" | TextContent + logger.warning |
| Erreur inattendue | Exception | "Unexpected: {e}" | TextContent + logger.exception |
