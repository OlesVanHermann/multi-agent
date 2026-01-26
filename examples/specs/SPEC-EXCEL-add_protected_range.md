# SPEC-EXCEL-add_protected_range

## Date: 20260125
## Auteur: Explorer (200)
## Source: DOC-EXCEL-lot1.md

## Fonction a implementer

| Fonction MCP | Methode API | Description |
|--------------|-------------|-------------|
| excel_add_protected_range | ApiWorksheet.AddProtectedRange() | Cree une plage protegee a partir de la plage de donnees selectionnee |

## Details API

- **Classe:** ApiWorksheet
- **Methode:** AddProtectedRange()
- **Parametres:** sTitle (string), sDataRange (string)
- **Retour:** ApiProtectedRange | null

## Parametres MCP

| Parametre | Type | Requis | Description |
|-----------|------|--------|-------------|
| file_path | string | Oui | Chemin du fichier Excel |
| sheet | string/number | Non | Nom ou index de la feuille (defaut: feuille active) |
| title | string | Oui | Titre de la plage protegee |
| data_range | string | Oui | Plage de cellules (ex: "Sheet1!$A$1:$B$1") |

## Code JS

```javascript
let worksheet = Api.GetActiveSheet();
worksheet.GetRange("A1").SetValue("1");
worksheet.GetRange("B1").SetValue("2");
worksheet.AddProtectedRange("protectedRange", "Sheet1!$A$1:$B$1");
```

## Exemple d'appel MCP

```json
{
  "tool": "excel_add_protected_range",
  "arguments": {
    "file_path": "/path/to/file.xlsx",
    "title": "SensitiveData",
    "data_range": "Sheet1!$A$1:$B$10"
  }
}
```

## Retour attendu

```json
{
  "success": true,
  "data": {
    "title": "SensitiveData",
    "range": "Sheet1!$A$1:$B$10",
    "message": "Protected range created"
  }
}
```
