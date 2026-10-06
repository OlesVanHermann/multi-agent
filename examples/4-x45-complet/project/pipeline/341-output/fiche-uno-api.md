# Fiche analyse : API UNO CellProperties

## Éléments identifiés
| Élément | Type complet | Description | Exemple |
|---------|-------------|-------------|---------|
| CellBackColor | long (int32) | Couleur de fond RGB | 0xFF0000 = rouge |
| IsCellBackgroundTransparent | boolean | Fond transparent si true | true/false |

## Fonctions d'accès
- getCellByPosition(col: int, row: int) → com.sun.star.table.XCell
- getCellRangeByName(address: str) → com.sun.star.table.XCellRange
- getSheets() → com.sun.star.sheet.XSpreadsheets
- getByName(name: str) → com.sun.star.sheet.XSpreadsheet
- getByIndex(index: int) → com.sun.star.sheet.XSpreadsheet
- getCurrentComponent() → com.sun.star.lang.XComponent | None

## Conversion couleur
- Hex string → int : int("FF0000", 16) → 16711680
- int → RGB : r=(c>>16)&0xFF, g=(c>>8)&0xFF, b=c&0xFF
- RGB → int : (r<<16) + (g<<8) + b

## Exceptions et erreurs
| Exception (module) | Condition | Description |
|-------------------|-----------|-------------|
| com.sun.star.container.NoSuchElementException | getByName("inexistant") | Feuille non trouvée |
| com.sun.star.lang.IllegalArgumentException | getCellRangeByName("!!!") | Adresse cellule invalide |
| ConnectionRefusedError (Python) | socket connexion port 2002 | LibreOffice non lancé ou port fermé |
| RuntimeException (UNO) | bridge perdu | Connexion UNO interrompue |
| None (pas exception) | getCurrentComponent() | Aucun document ouvert, retourne None |

## Sources
- uno-01 : clean/uno-api.md#CellProperties
- uno-02 : clean/uno-api.md#AccesCellule
- uno-03 : clean/uno-api.md#Couleur
- uno-04 : clean/uno-api.md#Connexion
- uno-05 : clean/uno-api.md#Navigation
