# PR-SPEC-300-ApiRange_Copy

## Source
spreadsheet-api/ApiRange/Methods/Copy.md

## Fonction MCP
excel_range_copy

## API OnlyOffice
ApiRange.Copy()

## Description
Copie le contenu de la plage de cellules sélectionnée vers une autre plage.

## Paramètres

| Param | Type | Requis | Description |
|-------|------|--------|-------------|
| file_path | string | Oui | Chemin du fichier Excel |
| source_range | string | Oui | Plage source (ex: "A1:B10") |
| dest_range | string | Oui | Plage destination (ex: "D1:E10") |

## Code JS (pour CDP)

```javascript
var oWorksheet = Api.GetActiveSheet();
var oRange = oWorksheet.GetRange("A1:B10");
oRange.Copy(oWorksheet.GetRange("D1:E10"));
```

## Retour

```json
{
  "success": true,
  "result": {
    "copied": true,
    "source": "A1:B10",
    "destination": "D1:E10"
  }
}
```

## Créé par
200 (Explorer)

## Date
2026-01-25
