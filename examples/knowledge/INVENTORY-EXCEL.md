# Inventaire API Excel (spreadsheet-api)

**Date:** 24 jan 2026
**Agent:** 07 - Doc Explorer
**Source:** `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/spreadsheet-api/`

---

## Résumé

| Métrique | Valeur |
|----------|--------|
| Classes | 62 |
| Méthodes totales | ~1350 |
| Implémenté | 54 outils |
| Coverage | ~4% |

---

## Classes par nombre de méthodes

| Classe | Méthodes | Priorité | Notes |
|--------|----------|----------|-------|
| ApiWorksheetFunction | 415 | LOW | Fonctions Excel (SUM, AVERAGE, etc.) |
| Api | 84 | HIGH | Méthodes globales |
| ApiRange | 80 | HIGH | Manipulation cellules - CRITIQUE |
| ApiWorksheet | 60 | HIGH | Gestion feuilles |
| ApiPivotTable | 59 | LOW | Tableaux croisés dynamiques |
| ApiDatabar | 59 | LOW | Barres de données |
| ApiPivotDataField | 58 | LOW | Champs pivot |
| ApiPivotField | 53 | LOW | Champs pivot |
| ApiParagraph | 52 | MEDIUM | Paragraphes (texte) |
| ApiRun | 43 | MEDIUM | Texte formaté |
| ApiChart | 43 | MEDIUM | Graphiques |
| ApiIconSetCondition | 38 | LOW | Mise en forme conditionnelle |
| ApiTop10 | 34 | LOW | Top 10 conditionnel |
| ApiAboveAverage | 32 | LOW | Au-dessus moyenne |
| ApiCore | 31 | LOW | Métadonnées document |
| ApiUniqueValues | 30 | LOW | Valeurs uniques |
| ApiColorScale | 29 | LOW | Échelle de couleurs |
| ApiTextPr | 28 | LOW | Propriétés texte |
| ApiFormatCondition | 28 | MEDIUM | Mise en forme conditionnelle |
| ApiParaPr | 20 | LOW | Propriétés paragraphe |
| ApiComment | 20 | MEDIUM | Commentaires |
| ApiFont | 19 | MEDIUM | Police |
| ApiCustomXmlNode | 18 | LOW | XML personnalisé |
| ApiPath | 17 | LOW | Chemins |
| ApiPathCommand | 13 | LOW | Commandes chemin |
| ApiGeometry | 12 | LOW | Géométrie |
| ApiDrawing | 12 | MEDIUM | Dessins |
| ApiDocumentContent | 12 | LOW | Contenu document |
| ApiCustomXmlPart | 12 | LOW | XML personnalisé |
| ApiFormatConditions | 11 | MEDIUM | Collection conditions |
| ApiCommentReply | 11 | LOW | Réponses commentaires |
| ApiHyperlink | 10 | MEDIUM | Liens hypertexte |
| ApiIconCriterion | 9 | LOW | Critères icônes |
| ApiCharacters | 9 | LOW | Caractères |
| ApiWorkbook | 8 | HIGH | Classeur |
| ApiShape | 7 | MEDIUM | Formes |
| ApiProtectedRange | 7 | LOW | Plages protégées |
| ApiColorScaleCriterion | 7 | LOW | Critères échelle |
| ApiPivotItem | 6 | LOW | Éléments pivot |
| ApiName | 6 | MEDIUM | Plages nommées |
| ApiCustomXmlParts | 6 | LOW | XML personnalisé |
| ApiOleObject | 5 | LOW | Objets OLE |
| ApiFreezePanes | 5 | MEDIUM | Volets figés |
| ApiProtectedRangeUserInfo | 3 | LOW | Info utilisateur |
| ApiCustomProperties | 3 | LOW | Propriétés custom |
| ApiChartSeries | 3 | MEDIUM | Séries graphique |
| ApiAreas | 3 | LOW | Zones |
| ApiTheme | 2 | LOW | Thème |
| ApiColor | 2 | LOW | Couleur |
| ApiUnsupported | 1 | - | Non supporté |
| ApiUniColor | 1 | LOW | Couleur unie |
| ApiTable | 1 | MEDIUM | Tableaux |
| ApiStroke | 1 | LOW | Contour |
| ApiSchemeColor | 1 | LOW | Couleur schéma |
| ApiRGBColor | 1 | LOW | Couleur RGB |
| ApiPresetColor | 1 | LOW | Couleur prédéfinie |
| ApiPivotFilters | 1 | LOW | Filtres pivot |
| ApiImage | 1 | MEDIUM | Images |
| ApiGradientStop | 1 | LOW | Arrêt dégradé |
| ApiFill | 1 | LOW | Remplissage |
| ApiBullet | 1 | LOW | Puces |

---

## Fonctionnalités implémentées (54)

| Outil MCP | Description | Phase |
|-----------|-------------|-------|
| `excel_cell_edit` | Éditer cellule | Base |
| `excel_cell_get` | Lire cellule | Base |
| `excel_row_add` | Ajouter ligne | Base |
| `excel_column_add` | Ajouter colonne | Base |
| `excel_column_delete` | Supprimer colonne | Base |
| `excel_range_set` | Définir plage | Base |
| `excel_cell_bold` | Gras | Phase 1 |
| `excel_cell_italic` | Italique | Phase 1 |
| `excel_cell_underline` | Souligné | Phase 1 |
| `excel_cell_font_size` | Taille police | Phase 1 |
| `excel_cell_font_name` | Nom police | Phase 1 |
| `excel_cell_font_color` | Couleur police | Phase 1 |
| `excel_cell_fill_color` | Couleur fond | Phase 1 |
| `excel_cell_align` | Alignement | Phase 1 |
| `excel_cell_border` | Bordures | Phase 2 |
| `excel_cell_number_format` | Format nombres | Phase 2 |
| `excel_cell_wrap` | Retour ligne | Phase 2 |
| `excel_merge_cells` | Fusionner | Phase 2 |
| `excel_unmerge_cells` | Défusionner | Phase 2 |
| `excel_row_height` | Hauteur ligne | Phase 3 |
| `excel_column_width` | Largeur colonne | Phase 3 |
| `excel_row_delete` | Supprimer ligne | Phase 3 |
| `excel_row_insert` | Insérer ligne | Phase 3 |
| `excel_column_insert` | Insérer colonne | Phase 3 |
| `excel_autofit` | Auto-ajuster | Phase 3 |
| `excel_formula_set` | Définir formule | Phase 4 |
| `excel_formula_get` | Lire formule | Phase 4 |
| `excel_recalculate` | Recalculer | Phase 4 |
| `excel_sheet_add` | Ajouter feuille | Phase 5 |
| `excel_sheet_delete` | Supprimer feuille | Phase 5 |
| `excel_sheet_rename` | Renommer feuille | Phase 5 |
| `excel_sheet_list` | Lister feuilles | Phase 5 |
| `excel_sheet_activate` | Activer feuille | Phase 5 |
| `excel_find` | Rechercher | Phase 6 |
| `excel_sort` | Trier | Phase 6 |
| `excel_filter_toggle` | Filtrer | Phase 6 |
| `excel_clear` | Effacer | Phase 6 |
| `excel_chart_add` | Graphique | Phase 7 |
| `excel_image_add` | Image | Phase 7 |
| `excel_pivot_create` | Créer pivot table | Phase 11 |
| `excel_pivot_add_fields` | Ajouter champs pivot | Phase 11 |
| `excel_pivot_add_data_field` | Ajouter champ valeurs | Phase 11 |
| `excel_pivot_refresh` | Rafraîchir pivot | Phase 11 |
| `excel_pivot_get_name` | Nom pivot | Phase 11 |
| `excel_pivot_set_name` | Définir nom pivot | Phase 11 |
| `excel_pivot_clear` | Vider pivot | Phase 11 |
| `excel_pivot_set_style` | Style pivot | Phase 11 |
| `excel_hyperlink_add` | Ajouter hyperlien | Phase 11 |
| `excel_hyperlink_get` | Lire hyperlien | Phase 11 |
| `excel_hyperlink_remove` | Supprimer hyperlien | Phase 11 |
| `excel_hyperlink_set_tooltip` | Info-bulle hyperlien | Phase 11 |
| `excel_hyperlink_set_display` | Texte affiché | Phase 11 |
| `excel_hyperlink_set_link` | Modifier URL | Phase 12 |
| `excel_hyperlink_get_tooltip` | Lire info-bulle | Phase 12 |

---

## Priorités pour v1.2

### HIGH - Classes critiques à explorer

#### ApiRange (80 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetValue | ✅ | - |
| SetValue | ✅ | - |
| GetFormula | ✅ | - |
| SetFormula | ✅ | - |
| Copy | ❌ | HIGH |
| Paste | ❌ | HIGH |
| Cut | ❌ | HIGH |
| Delete | ❌ | HIGH |
| Insert | ❌ | HIGH |
| GetAddress | ❌ | MEDIUM |
| GetRow | ❌ | MEDIUM |
| GetColumn | ❌ | MEDIUM |
| GetCount | ❌ | MEDIUM |
| Select | ❌ | MEDIUM |

#### ApiWorksheet (60 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetRange | ✅ | - |
| GetName | ✅ | - |
| SetName | ✅ | - |
| GetCells | ❌ | HIGH |
| GetUsedRange | ❌ | HIGH |
| GetActiveCell | ❌ | HIGH |
| SetColumnWidth | ✅ | - |
| SetRowHeight | ✅ | - |
| AddChart | ✅ | - |
| GetCharts | ❌ | MEDIUM |
| Protect | ❌ | MEDIUM |
| Unprotect | ❌ | MEDIUM |

#### Api (84 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetActiveSheet | ✅ | - |
| GetSheets | ✅ | - |
| AddSheet | ✅ | - |
| CreateChart | ✅ | - |
| CreateRange | ❌ | HIGH |
| CreateNewHistoryPoint | ❌ | MEDIUM |
| GetSelection | ❌ | HIGH |
| Save | ✅ | - |

### MEDIUM - Fonctionnalités complémentaires

- ApiComment: Gestion commentaires
- ApiHyperlink: Liens hypertexte
- ApiChart: Configuration graphiques avancée
- ApiFormatCondition: Mise en forme conditionnelle
- ApiName: Plages nommées
- ApiFreezePanes: Volets figés

### LOW - Fonctionnalités avancées

- ApiPivotTable: Tableaux croisés dynamiques
- ApiWorksheetFunction: Fonctions Excel (415 méthodes!)
- ApiDatabar: Barres de données conditionnelles

---

## Statistiques finales

| Priorité | Classes | Méthodes estimées |
|----------|---------|-------------------|
| HIGH | 4 | ~230 |
| MEDIUM | 12 | ~200 |
| LOW | 46 | ~920 |
| **Total** | **62** | **~1350** |

**Prochaines fonctions recommandées:** Copy/Paste, GetUsedRange, GetSelection, Protect
