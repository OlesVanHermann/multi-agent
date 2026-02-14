# Inventaire API PowerPoint (presentation-api)

**Date:** 24 jan 2026
**Agent:** 07 - Doc Explorer
**Source:** `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/presentation-api/`

---

## Résumé

| Métrique | Valeur |
|----------|--------|
| Classes | 48 |
| Méthodes totales | ~650 |
| Implémenté | 49 outils |
| Coverage | ~7.5% |

---

## Classes par nombre de méthodes

| Classe | Méthodes | Priorité | Notes |
|--------|----------|----------|-------|
| Api | 61 | HIGH | Méthodes globales |
| ApiParagraph | 54 | HIGH | Paragraphes texte |
| ApiRun | 44 | HIGH | Texte formaté |
| ApiChart | 44 | MEDIUM | Graphiques |
| ApiSlide | 34 | HIGH | Slides - CRITIQUE |
| ApiPresentation | 34 | HIGH | Présentation |
| ApiCore | 31 | LOW | Métadonnées |
| ApiTextPr | 30 | MEDIUM | Propriétés texte |
| ApiMaster | 25 | MEDIUM | Masques |
| ApiLayout | 23 | MEDIUM | Layouts |
| ApiParaPr | 20 | LOW | Propriétés paragraphe |
| ApiComment | 20 | MEDIUM | Commentaires |
| ApiDrawing | 19 | MEDIUM | Dessins |
| ApiCustomXmlNode | 18 | LOW | XML personnalisé |
| ApiPath | 17 | LOW | Chemins |
| ApiTable | 13 | MEDIUM | Tableaux |
| ApiTableCell | 13 | MEDIUM | Cellules tableau |
| ApiPathCommand | 13 | LOW | Commandes chemin |
| ApiGeometry | 12 | LOW | Géométrie |
| ApiDocumentContent | 12 | LOW | Contenu |
| ApiCustomXmlPart | 12 | LOW | XML personnalisé |
| ApiHyperlink | 10 | MEDIUM | Liens |
| ApiTheme | 8 | LOW | Thème |
| ApiThemeFormatScheme | 7 | LOW | Schéma format |
| ApiShape | 6 | HIGH | Formes |
| ApiCustomXmlParts | 6 | LOW | XML personnalisé |
| ApiCommentReply | 6 | LOW | Réponses commentaires |
| ApiThemeFontScheme | 5 | LOW | Schéma police |
| ApiThemeColorScheme | 5 | LOW | Schéma couleur |
| ApiPlaceholder | 5 | MEDIUM | Placeholders |
| ApiOleObject | 5 | LOW | Objets OLE |
| ApiTableRow | 4 | MEDIUM | Lignes tableau |
| ApiSelection | 4 | MEDIUM | Sélection |
| ApiNotesPage | 4 | LOW | Notes |
| ApiCustomProperties | 3 | LOW | Propriétés custom |
| ApiChartSeries | 3 | LOW | Séries graphique |
| ApiGroup | 2 | LOW | Groupes |
| ApiUnsupported | 1 | - | Non supporté |
| ApiUniColor | 1 | LOW | Couleur |
| ApiStroke | 1 | LOW | Contour |
| ApiSchemeColor | 1 | LOW | Couleur schéma |
| ApiRGBColor | 1 | LOW | Couleur RGB |
| ApiPresetColor | 1 | LOW | Couleur prédéfinie |
| ApiImage | 1 | MEDIUM | Images |
| ApiGradientStop | 1 | LOW | Dégradé |
| ApiFill | 1 | LOW | Remplissage |
| ApiBullet | 1 | LOW | Puces |

---

## Fonctionnalités implémentées (37)

| Outil MCP | Description | Phase |
|-----------|-------------|-------|
| `pptx_slide_add` | Ajouter slide | Base |
| `pptx_slide_set_title` | Définir titre | Base |
| `pptx_text_add` | Ajouter texte | Base |
| `pptx_shape_add` | Ajouter forme | Base |
| `pptx_slide_delete` | Supprimer slide | Phase 1 |
| `pptx_slide_duplicate` | Dupliquer slide | Phase 1 |
| `pptx_slide_move` | Déplacer slide | Phase 1 |
| `pptx_goto_slide` | Naviguer slide | Phase 1 |
| `pptx_slide_count` | Compter slides | Phase 1 |
| `pptx_slide_background` | Fond slide | Phase 1 |
| `pptx_slide_clear` | Vider slide | Phase 1 |
| `pptx_textbox_add` | Textbox formatée | Phase 2 |
| `pptx_shape_rect` | Rectangle | Phase 2 |
| `pptx_shape_ellipse` | Ellipse | Phase 2 |
| `pptx_shape_arrow` | Flèche | Phase 2 |
| `pptx_line_add` | Ligne | Phase 2 |
| `pptx_image_add` | Image | Phase 2 |
| `pptx_table_add` | Tableau | Phase 2 |
| `pptx_chart_add` | Graphique | Phase 2 |
| `pptx_transition_set` | Transition | Phase 3 |
| `pptx_animation_add` | Animation | Phase 3 |
| `pptx_master_apply` | Appliquer layout | Phase 3 |
| `pptx_get_layouts` | Lister layouts | Phase 3 |
| `pptx_shape_set_rotation` | Pivoter shape | Phase 4 |
| `pptx_shape_get_rotation` | Angle rotation | Phase 4 |
| `pptx_text_valign` | Alignement vertical | Phase 4 |
| `pptx_shape_copy` | Copier shape | Phase 4 |
| `pptx_shape_lock` | Verrouiller shape | Phase 4 |
| `pptx_shape_to_json` | Export JSON | Phase 4 |
| `pptx_notes_set` | Définir notes | Phase 7 |
| `pptx_notes_get` | Lire notes | Phase 7 |
| `pptx_notes_clear` | Effacer notes | Phase 7 |
| `pptx_comment_add_reply` | Répondre commentaire | Phase 7 |
| `pptx_comment_set_text` | Modifier commentaire | Phase 7 |
| `pptx_comment_delete` | Supprimer commentaire | Phase 7 |
| `pptx_notes_add_text` | Ajouter texte notes | Phase 7 |
| `pptx_notes_get_text` | Lire texte notes | Phase 7 |
| `pptx_get_width` | Largeur présentation | Phase 8 |
| `pptx_get_height` | Hauteur présentation | Phase 8 |
| `pptx_set_sizes` | Définir dimensions | Phase 8 |
| `pptx_drawing_get_width` | Largeur drawing | Phase 8 |
| `pptx_drawing_get_height` | Hauteur drawing | Phase 8 |
| `pptx_drawing_copy` | Copier drawing | Phase 8 |
| `pptx_get_size` | Dimensions complètes | Phase 8 |
| `pptx_slide_get_index` | Index de slide | Phase 8 |
| `pptx_slide_get_layout` | Layout de slide | Phase 8 |
| `pptx_drawing_get_rotation` | Angle rotation drawing | Phase 8 |
| `pptx_drawing_delete` | Supprimer drawing | Phase 8 |
| `pptx_drawing_get_class_type` | Type drawing | Phase 8 |

---

## Priorités pour v1.2

### HIGH - Classes critiques à explorer

#### ApiSlide (34 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| AddObject | ✅ | - |
| RemoveObject | ✅ | - |
| GetAllDrawings | ✅ | - |
| GetAllShapes | ✅ | - |
| GetAllImages | ✅ | - |
| GetAllCharts | ✅ | - |
| Copy | ✅ | - |
| ApplyTheme | ❌ | MEDIUM |
| GetBackground | ❌ | MEDIUM |
| GetLayout | ❌ | MEDIUM |

#### ApiPresentation (34 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetSlideByIndex | ✅ | - |
| GetSlidesCount | ✅ | - |
| AddSlide | ✅ | - |
| GetCurrentSlide | ✅ | - |
| GetAllSlides | ✅ | - |
| SetSizes | ✅ | - |
| GetWidth | ✅ | - |
| GetHeight | ✅ | - |
| ToJSON | ❌ | LOW |

#### ApiShape (6 méthodes)
| Méthode | Implémenté | Priorité |
|---------|------------|----------|
| GetContent | ✅ | - |
| SetPosition | ✅ | - |
| SetSize | ✅ | - |
| GetDocContent | ❌ | MEDIUM |
| SetVerticalTextAlign | ✅ | - |
| GetClassType | ❌ | LOW |

### MEDIUM - Fonctionnalités complémentaires

- ApiMaster: Masques de diapositive
- ApiLayout: Layouts personnalisés
- ApiTable: Manipulation tableaux
- ApiChart: Configuration graphiques
- ApiComment: Commentaires
- ApiPlaceholder: Placeholders

---

## Statistiques finales

| Priorité | Classes | Méthodes estimées |
|----------|---------|-------------------|
| HIGH | 6 | ~230 |
| MEDIUM | 14 | ~220 |
| LOW | 28 | ~200 |
| **Total** | **48** | **~650** |

**Prochaines fonctions recommandées:** ApplyTheme, GetBackground, GetLayout, GetDocContent
