# SPEC-EXCEL-get_all_charts - Récupération de tous les graphiques

## Fonctions à implémenter

| Fonction | API | Description |
|----------|-----|-------------|
| excel_get_all_charts | ApiWorksheet.GetAllCharts | Retourne tous les graphiques d'une feuille |

## Détails API

### excel_get_all_charts

- **Classe:** ApiWorksheet
- **Méthode:** GetAllCharts()
- **Paramètres:** Aucun
- **Retour:** ApiChart[]
- **Description:** Retourne un tableau contenant tous les objets graphiques (charts) présents dans la feuille de calcul courante.

### Exemple API OnlyOffice

```javascript
let worksheet = Api.GetActiveSheet();

// Créer des données
worksheet.GetRange("B1").SetValue(2014);
worksheet.GetRange("C1").SetValue(2015);
worksheet.GetRange("D1").SetValue(2016);
worksheet.GetRange("A2").SetValue("Projected Revenue");
worksheet.GetRange("A3").SetValue("Estimated Costs");
worksheet.GetRange("B2").SetValue(200);
worksheet.GetRange("B3").SetValue(250);
worksheet.GetRange("C2").SetValue(240);
worksheet.GetRange("C3").SetValue(260);
worksheet.GetRange("D2").SetValue(280);
worksheet.GetRange("D3").SetValue(280);

// Ajouter un graphique
let chart = worksheet.AddChart("'Sheet1'!$A$1:$D$3", true, "bar3D", 2, 100 * 36000, 70 * 36000, 0, 2 * 36000, 7, 3 * 36000);
chart.SetTitle("Financial Overview", 13);

// Récupérer tous les graphiques
let charts = worksheet.GetAllCharts();
// charts[0] est le graphique créé
```

## Paramètres MCP

| Fonction | Paramètres | Retour |
|----------|------------|--------|
| excel_get_all_charts | `sheet_name?: string` | JSON array d'objets chart |

### Paramètres détaillés

| Paramètre | Type | Requis | Description |
|-----------|------|--------|-------------|
| sheet_name | string | Non | Nom de la feuille. Si omis, utilise la feuille active. |

### Format de retour

```json
{
  "success": true,
  "charts": [
    {
      "index": 0,
      "type": "bar3D",
      "title": "Financial Overview",
      "class_type": "chart"
    },
    {
      "index": 1,
      "type": "line",
      "title": "Sales Trend",
      "class_type": "chart"
    }
  ],
  "count": 2
}
```

## Propriétés ApiChart disponibles

L'objet ApiChart retourné expose les méthodes suivantes pour obtenir des informations:

| Méthode | Retour | Description |
|---------|--------|-------------|
| GetClassType() | "chart" | Type de classe |
| GetChartType() | ChartType | Type du graphique (bar, line, pie, etc.) |
| GetAllSeries() | ApiChartSeries[] | Toutes les séries du graphique |
| GetSeries(index) | ApiChartSeries | Série à l'index spécifié |

## Types de graphiques (ChartType)

- `bar` - Graphique à barres
- `barStacked` - Barres empilées
- `bar3D` - Barres 3D
- `line` - Graphique linéaire
- `lineStacked` - Lignes empilées
- `pie` - Camembert
- `pie3D` - Camembert 3D
- `scatter` - Nuage de points
- `area` - Graphique en aires
- `areaStacked` - Aires empilées
- `doughnut` - Anneau
- `stock` - Graphique boursier
- `radar` - Radar

## Implémentation suggérée

```typescript
async function excel_get_all_charts(params: { sheet_name?: string }): Promise<Result> {
  const script = `
    let worksheet = ${params.sheet_name
      ? `Api.GetSheet("${params.sheet_name}")`
      : 'Api.GetActiveSheet()'};

    if (!worksheet) {
      return { success: false, error: "Sheet not found" };
    }

    let charts = worksheet.GetAllCharts();
    let result = [];

    for (let i = 0; i < charts.length; i++) {
      let chart = charts[i];
      result.push({
        index: i,
        type: chart.GetChartType(),
        class_type: chart.GetClassType()
      });
    }

    return {
      success: true,
      charts: result,
      count: result.length
    };
  `;

  return await executeScript(script);
}
```

## Notes d'implémentation

1. La méthode `GetAllCharts()` ne prend aucun paramètre
2. Le retour est un tableau vide `[]` si aucun graphique n'existe
3. Les graphiques sont retournés dans l'ordre de leur création
4. Chaque ApiChart peut être manipulé pour modifier ses propriétés (couleurs, titre, séries, etc.)

## Cas d'utilisation

- Lister tous les graphiques d'un classeur pour inventaire
- Appliquer un style uniforme à tous les graphiques
- Exporter la liste des graphiques pour documentation
- Vérifier l'existence de graphiques avant manipulation

## Référence

- Documentation API: `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/spreadsheet-api/ApiWorksheet/Methods/GetAllCharts.md`
- Classe ApiChart: `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/spreadsheet-api/ApiChart/ApiChart.md`
