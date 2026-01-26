# Inventaire API Word (text-document-api)

**Date:** 24 jan 2026
**Agent:** 07 - Doc Explorer
**Source:** `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/text-document-api/`

---

## Résumé

| Métrique | Valeur |
|----------|--------|
| Classes | 59 |
| Méthodes totales | ~1400 |
| Implémenté | 36 outils |
| Coverage | ~2.6% |

---

## Classes par nombre de méthodes

| Classe | Méthodes | Priorité | Notes |
|--------|----------|----------|-------|
| ApiDocument | 125 | HIGH | Document principal - CRITIQUE |
| ApiParagraph | 110 | HIGH | Paragraphes - CRITIQUE |
| Api | 72 | HIGH | Méthodes globales |
| ApiRun | 64 | HIGH | Texte formaté |
| ApiTable | 61 | HIGH | Tableaux |
| ApiInlineLvlSdt | 60 | LOW | Contrôles inline |
| ApiBlockLvlSdt | 51 | LOW | Contrôles bloc |
| ApiChart | 48 | MEDIUM | Graphiques |
| ApiTextPr | 40 | MEDIUM | Propriétés texte |
| ApiRange | 40 | MEDIUM | Plages |
| ApiTextForm | 38 | LOW | Formulaires (PDF) |
| ApiPictureForm | 38 | LOW | Formulaires (PDF) |
| ApiCheckBoxForm | 37 | LOW | Formulaires (PDF) |
| ApiDateForm | 36 | LOW | Formulaires (PDF) |
| ApiTableCell | 35 | HIGH | Cellules tableau |
| ApiParaPr | 35 | MEDIUM | Propriétés paragraphe |
| ApiDrawing | 35 | MEDIUM | Dessins/images |
| ApiComboBoxForm | 33 | LOW | Formulaires (PDF) |
| ApiCore | 31 | LOW | Métadonnées |
| ApiComplexForm | 31 | LOW | Formulaires (PDF) |
| ApiFormBase | 28 | LOW | Formulaires (PDF) |
| ApiSection | 27 | MEDIUM | Sections |
| ApiTablePr | 25 | MEDIUM | Propriétés tableau |
| ApiDocumentContent | 23 | LOW | Contenu document |
| ApiComment | 20 | MEDIUM | Commentaires |
| ApiTableRow | 18 | HIGH | Lignes tableau |
| ApiStyle | 18 | MEDIUM | Styles |
| ApiCustomXmlNode | 18 | LOW | XML personnalisé |
| ApiPath | 17 | LOW | Chemins |
| ApiWatermarkSettings | 16 | MEDIUM | Filigranes |
| ApiTableCellPr | 15 | MEDIUM | Propriétés cellule |
| ApiTableStylePr | 13 | LOW | Styles tableau |
| ApiPathCommand | 13 | LOW | Commandes chemin |
| ApiHyperlink | 12 | MEDIUM | Liens |
| ApiGeometry | 12 | LOW | Géométrie |
| ApiCustomXmlPart | 12 | LOW | XML personnalisé |
| ApiContentControlListEntry | 12 | LOW | Entrées liste |
| ApiNumberingLevel | 11 | MEDIUM | Niveaux numérotation |
| ApiShape | 8 | MEDIUM | Formes |
| ApiBookmark | 8 | MEDIUM | Signets |
| ApiContentControlList | 7 | LOW | Listes contrôle |
| ApiCommentReply | 7 | LOW | Réponses commentaires |
| ApiCustomXmlParts | 6 | LOW | XML personnalisé |
| ApiOleObject | 5 | LOW | Objets OLE |
| ApiTableRowPr | 4 | LOW | Propriétés ligne |
| ApiUniColor | 3 | LOW | Couleur |
| ApiNumbering | 3 | MEDIUM | Numérotation |
| ApiImage | 3 | MEDIUM | Images |
| ApiCustomProperties | 3 | LOW | Propriétés custom |
| ApiChartSeries | 3 | LOW | Séries graphique |
| ApiStroke | 2 | LOW | Contour |
| ApiSchemeColor | 2 | LOW | Couleur schéma |
| ApiRGBColor | 2 | LOW | Couleur RGB |
| ApiPresetColor | 2 | LOW | Couleur prédéfinie |
| ApiGroup | 2 | LOW | Groupes |
| ApiGradientStop | 2 | LOW | Dégradé |
| ApiFill | 2 | LOW | Remplissage |
| ApiUnsupported | 1 | - | Non supporté |

---

## Fonctionnalités implémentées (36)

| Outil MCP | Description | Phase |
|-----------|-------------|-------|
| `word_paragraph_add` | Ajouter paragraphe | Base |
| `word_table_add` | Ajouter tableau | Base |
| `word_text_insert` | Insérer texte | Base |
| `word_heading_add` | Ajouter titre | Base |
| `word_page_break` | Saut de page | Base |
| `word_line_break` | Saut de ligne | Base |
| `word_search_replace` | Rechercher/remplacer | Base |
| `word_page_count` | Compter pages | Base |
| `word_goto_page` | Naviguer page | Base |
| `word_get_text` | Obtenir texte | Base |
| `word_list_add` | Liste puces/numéros | Phase 2 |
| `word_text_formatted` | Texte formaté | Phase 2 |
| `word_image_insert` | Insérer image | Phase 2 |
| `word_horizontal_rule` | Ligne horizontale | Phase 2 |
| `word_paragraph_align` | Alignement | Phase 3 |
| `word_paragraph_indent` | Retrait | Phase 3 |
| `word_paragraph_spacing` | Espacement | Phase 3 |
| `word_paragraph_border` | Bordure | Phase 3 |
| `word_paragraph_shading` | Fond | Phase 3 |
| `word_paragraph_keep_together` | Lignes ensemble | Phase 3 |
| `word_paragraph_page_break_before` | Saut avant | Phase 3 |
| `word_header_set` | Définir en-tête | Phase 7 |
| `word_footer_set` | Définir pied de page | Phase 7 |
| `word_header_remove` | Supprimer en-tête | Phase 7 |
| `word_footer_remove` | Supprimer pied de page | Phase 7 |
| `word_title_page` | Page de titre | Phase 7 |
| `word_page_margins` | Marges page | Phase 7 |
| `word_comment_add` | Ajouter commentaire | Phase 8 |
| `word_comments_get_all` | Lister commentaires | Phase 8 |
| `word_bookmark_add` | Ajouter signet | Phase 8 |
| `word_bookmark_goto` | Naviguer vers signet | Phase 8 |
| `word_hyperlink_add` | Ajouter lien | Phase 8 |
| `word_watermark_set_text` | Filigrane texte | Phase 9 |
| `word_watermark_set_image` | Filigrane image | Phase 9 |
| `word_bookmark_get_range` | Texte d'un signet | Phase 9 |
| `word_bookmark_set_text` | Modifier texte signet | Phase 9 |

---

## Priorités pour v1.2

### HIGH - Classes critiques à explorer

#### ApiDocument (125 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetAllParagraphs | ❌ | HIGH |
| GetAllTables | ❌ | HIGH |
| GetElement | ❌ | HIGH |
| GetElementsCount | ❌ | HIGH |
| InsertContent | ❌ | HIGH |
| RemoveElement | ❌ | HIGH |
| CreateSection | ❌ | MEDIUM |
| GetSections | ❌ | MEDIUM |
| CreateStyle | ❌ | MEDIUM |
| GetStyles | ❌ | MEDIUM |
| AddTableOfContents | ❌ | MEDIUM |
| SetTrackRevisions | ❌ | LOW |

#### ApiParagraph (110 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| AddText | ✅ | - |
| SetBold | ❌ | HIGH |
| SetItalic | ❌ | HIGH |
| SetUnderline | ❌ | HIGH |
| SetFontSize | ❌ | HIGH |
| SetFontFamily | ❌ | HIGH |
| SetColor | ❌ | HIGH |
| SetHighlight | ❌ | MEDIUM |
| AddLineBreak | ✅ | - |
| AddPageBreak | ✅ | - |
| SetStyle | ❌ | MEDIUM |

#### ApiTable (61 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetRow | ❌ | HIGH |
| GetCell | ❌ | HIGH |
| AddRow | ❌ | HIGH |
| AddColumn | ❌ | HIGH |
| RemoveRow | ❌ | HIGH |
| RemoveColumn | ❌ | HIGH |
| MergeCells | ❌ | MEDIUM |
| SetWidth | ❌ | MEDIUM |
| SetTableBorderTop | ❌ | MEDIUM |

### MEDIUM - Fonctionnalités complémentaires

- ApiSection: En-têtes/pieds de page, marges
- ApiStyle: Styles personnalisés
- ApiComment: Commentaires et révisions
- ApiBookmark: Signets et navigation
- ApiHyperlink: Liens hypertexte
- ApiWatermarkSettings: Filigranes

---

## Statistiques finales

| Priorité | Classes | Méthodes estimées |
|----------|---------|-------------------|
| HIGH | 6 | ~450 |
| MEDIUM | 15 | ~350 |
| LOW | 38 | ~600 |
| **Total** | **59** | **~1400** |

**Prochaines fonctions recommandées:** GetAllParagraphs, Table manipulation, Text formatting inline
