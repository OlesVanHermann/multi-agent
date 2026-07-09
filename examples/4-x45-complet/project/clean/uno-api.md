# UNO API — CellProperties

## Service
`com.sun.star.table.CellProperties` (inclus dans `com.sun.star.sheet.SheetCell`)

## Propriétés pertinentes

| Propriété | Type | Description |
|-----------|------|-------------|
| `CellBackColor` | `long` (int32) | Couleur de fond RGB. -1 = transparent |
| `IsCellBackgroundTransparent` | `boolean` | Si true, fond transparent |

## Accès à une cellule

```python
cell = sheet.getCellByPosition(col, row)   # 0-indexed
cell = sheet.getCellRangeByName("A1")      # string address
```

## Manipulation couleur

```python
# Écrire
cell.CellBackColor = 0xFF0000  # rouge

# Lire
color = cell.CellBackColor
transparent = cell.IsCellBackgroundTransparent
```

## Conversion couleur

```python
# Hex string → int : int("FF0000", 16) → 16711680
# int → RGB : r=(c>>16)&0xFF, g=(c>>8)&0xFF, b=c&0xFF
# RGB → int : (r<<16) + (g<<8) + b
```

## Connexion UNO bridge

```python
import uno
from com.sun.star.beans import PropertyValue

localContext = uno.getComponentContext()
resolver = localContext.ServiceManager.createInstanceWithContext(
    "com.sun.star.bridge.UnoUrlResolver", localContext)
ctx = resolver.resolve(
    "uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext")
smgr = ctx.ServiceManager
desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
```

## Navigation document

```python
doc = desktop.getCurrentComponent()       # document actif
sheet = doc.getSheets().getByName("Sheet1")  # par nom
sheet = doc.getSheets().getByIndex(0)        # par index
```
