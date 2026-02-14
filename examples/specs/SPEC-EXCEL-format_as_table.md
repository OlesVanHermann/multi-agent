# SPEC-EXCEL-format_as_table

## Date: 20260125
## Auteur: Explorer (200)
## Source: DOC-EXCEL-lot1.md

## Fonction a implementer

| Fonction MCP | Methode API | Description |
|--------------|-------------|-------------|
| excel_format_as_table | ApiWorksheet.FormatAsTable() | Formate la plage selectionnee comme un tableau (premiere ligne = en-tete) |

## Details API

- **Classe:** ApiWorksheet
- **Methode:** FormatAsTable()
- **Parametres:** sRange (string)
- **Retour:** void

## Parametres MCP

| Parametre | Type | Requis | Description |
|-----------|------|--------|-------------|
| file_path | string | Oui | Chemin du fichier Excel |
| sheet | string/number | Non | Nom ou index de la feuille (defaut: feuille active) |
| range | string | Oui | Plage a formater (ex: "A1:E10") |

## Code JS

```javascript
let worksheet = Api.GetActiveSheet();
worksheet.FormatAsTable("A1:E10");
```

## Exemple d'appel MCP

```json
{
  "tool": "excel_format_as_table",
  "arguments": {
    "file_path": "/path/to/file.xlsx",
    "range": "A1:E10"
  }
}
```

## Retour attendu

```json
{
  "success": true,
  "data": {
    "message": "Range A1:E10 formatted as table"
  }
}
```
