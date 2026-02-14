# Inventaire API PDF (form-api)

**Date:** 24 jan 2026
**Agent:** 07 - Doc Explorer
**Source:** `/Users/claude/projet/api.onlyoffice.com/site/docs/office-api/usage-api/form-api/`

---

## Résumé

| Métrique | Valeur |
|----------|--------|
| Classes | 11 |
| Méthodes totales | 269 |
| Implémenté | 27 outils |
| Coverage | ~10% |

---

## Classes et Méthodes

### Api (6 méthodes) - Création de formulaires
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| CreateCheckBoxForm | ❌ | HIGH | Créer checkbox |
| CreateComboBoxForm | ❌ | HIGH | Créer dropdown |
| CreateComplexForm | ❌ | LOW | Formulaire complexe |
| CreateDateForm | ❌ | MEDIUM | Créer champ date |
| CreatePictureForm | ❌ | MEDIUM | Créer champ image |
| CreateTextForm | ❌ | HIGH | Créer champ texte |

### ApiDocument (13 méthodes) - Document PDF
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| ClearAllFields | 📋 SPEC | MEDIUM | `pdf_forms_clear_all` |
| GetAllForms | ✅ | - | `pdf_forms_get_all` |
| GetFormKeysByRole | ❌ | LOW | Clés par rôle |
| GetFormRoles | ❌ | LOW | Obtenir rôles |
| GetFormValueByKey | ✅ | - | `pdf_form_get_value` |
| GetFormsByKey | 📋 SPEC | MEDIUM | `pdf_forms_get_by_key` |
| GetFormsByRole | ❌ | LOW | Formulaires par rôle |
| GetFormsByTag | ❌ | MEDIUM | Formulaires par tag |
| GetFormsData | ✅ | - | `pdf_forms_get_data` |
| GetTagsOfAllForms | ❌ | LOW | Tous les tags |
| InsertTextForm | ❌ | HIGH | Insérer champ texte |
| SetFormsData | ✅ | - | `pdf_forms_set_data` |
| SetFormsHighlight | ❌ | LOW | Surlignage formulaires |

### ApiFormBase (28 méthodes) - Base des formulaires
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ✅ | - | `pdf_form_clear` |
| Copy | ✅ | - | `pdf_form_copy` |
| Delete | ✅ | - | `pdf_form_delete` |
| GetClassType | ❌ | LOW | Type de classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | MEDIUM | Obtenir type |
| GetInternalId | ❌ | LOW | ID interne |
| GetPlaceholderText | ❌ | LOW | Texte placeholder |
| GetRole | ❌ | LOW | Obtenir rôle |
| GetTag | ❌ | LOW | Obtenir tag |
| GetText | 📋 SPEC | MEDIUM | `pdf_form_get_text` |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Texte info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsFixed | ❌ | LOW | Est fixe |
| IsRequired | ❌ | MEDIUM | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetBackgroundColor | 📋 SPEC | MEDIUM | `pdf_form_set_bg_color` |
| SetBorderColor | 📋 SPEC | MEDIUM | `pdf_form_set_border_color` |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetPlaceholderText | ❌ | MEDIUM | Définir placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Définir rôle |
| SetTag | ❌ | LOW | Définir tag |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Définir info-bulle |
| ToFixed | ❌ | LOW | Convertir en fixe |
| ToInline | ❌ | LOW | Convertir en inline |

### ApiTextForm (38 méthodes) - Champs texte
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ❌ | MEDIUM | Effacer |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetCharactersLimit | ❌ | LOW | Limite caractères |
| GetClassType | ❌ | LOW | Type classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type formulaire |
| GetInternalId | ❌ | LOW | ID interne |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRole | ❌ | LOW | Rôle |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | MEDIUM | Obtenir texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsAutoFit | ❌ | LOW | Auto-ajustement |
| IsComb | ❌ | LOW | Est comb |
| IsFixed | ❌ | LOW | Est fixe |
| IsMultiline | ❌ | LOW | Multi-ligne |
| IsRequired | ❌ | LOW | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetAutoFit | ❌ | LOW | Définir auto-fit |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetCellWidth | ❌ | LOW | Largeur cellule |
| SetCharactersLimit | ❌ | MEDIUM | Limite caractères |
| SetComb | ❌ | LOW | Définir comb |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetMultiline | ❌ | MEDIUM | Multi-ligne |
| SetPlaceholderText | ❌ | MEDIUM | Placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Définir rôle |
| SetTag | ❌ | LOW | Définir tag |
| SetText | ✅ | - | `pdf_form_set_text` |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiCheckBoxForm (37 méthodes) - Cases à cocher
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ❌ | MEDIUM | Effacer |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetChoiceName | ❌ | LOW | Nom choix |
| GetClassType | ❌ | LOW | Type classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type |
| GetInternalId | ❌ | LOW | ID interne |
| GetLabel | ❌ | MEDIUM | Obtenir label |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRadioGroup | ❌ | MEDIUM | Groupe radio |
| GetRole | ❌ | LOW | Rôle |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | LOW | Texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsChecked | ❌ | MEDIUM | Est coché |
| IsFixed | ❌ | LOW | Est fixe |
| IsRadioButton | ❌ | MEDIUM | Est radio |
| IsRequired | ❌ | LOW | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetChecked | ✅ | - | `pdf_form_set_checkbox` |
| SetChoiceName | ❌ | LOW | Nom choix |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetLabel | ❌ | MEDIUM | Définir label |
| SetPlaceholderText | ❌ | LOW | Placeholder |
| SetRadioGroup | ❌ | MEDIUM | Groupe radio |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Rôle |
| SetTag | ❌ | LOW | Tag |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiComboBoxForm (33 méthodes) - Listes déroulantes
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ❌ | MEDIUM | Effacer |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetClassType | ❌ | LOW | Type classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type |
| GetInternalId | ❌ | LOW | ID interne |
| GetListValues | ❌ | MEDIUM | Obtenir valeurs liste |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRole | ❌ | LOW | Rôle |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | MEDIUM | Obtenir texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsEditable | ❌ | LOW | Est éditable |
| IsFixed | ❌ | LOW | Est fixe |
| IsRequired | ❌ | LOW | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SelectListValue | ✅ | - | `pdf_form_select_option` |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetListValues | ❌ | HIGH | Définir valeurs liste |
| SetPlaceholderText | ❌ | MEDIUM | Placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Rôle |
| SetTag | ❌ | LOW | Tag |
| SetText | ❌ | MEDIUM | Définir texte |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiDateForm (36 méthodes) - Champs date
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ❌ | MEDIUM | Effacer |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetClassType | ❌ | LOW | Type classe |
| GetDate | ❌ | MEDIUM | Obtenir date |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type |
| GetFormat | ❌ | MEDIUM | Obtenir format |
| GetInternalId | ❌ | LOW | ID interne |
| GetLanguage | ❌ | LOW | Langue |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRole | ❌ | LOW | Rôle |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | LOW | Texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTime | ❌ | MEDIUM | Obtenir heure |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsFixed | ❌ | LOW | Est fixe |
| IsRequired | ❌ | LOW | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetDate | ❌ | HIGH | Définir date |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetFormat | ❌ | MEDIUM | Définir format |
| SetLanguage | ❌ | LOW | Langue |
| SetPlaceholderText | ❌ | MEDIUM | Placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Rôle |
| SetTag | ❌ | LOW | Tag |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTime | ❌ | MEDIUM | Définir heure |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiPictureForm (38 méthodes) - Champs image
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Clear | ❌ | MEDIUM | Effacer |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetClassType | ❌ | LOW | Type classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type |
| GetImage | ❌ | MEDIUM | Obtenir image |
| GetInternalId | ❌ | LOW | ID interne |
| GetPicturePosition | ❌ | LOW | Position image |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRole | ❌ | LOW | Rôle |
| GetScaleFlag | ❌ | LOW | Flag échelle |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | LOW | Texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsFixed | ❌ | LOW | Est fixe |
| IsLockAspectRatio | ❌ | LOW | Verrouiller ratio |
| IsRequired | ❌ | LOW | Est requis |
| IsRespectBorders | ❌ | LOW | Respecter bordures |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetImage | ❌ | HIGH | Définir image |
| SetLockAspectRatio | ❌ | LOW | Verrouiller ratio |
| SetPicturePosition | ❌ | LOW | Position image |
| SetPlaceholderText | ❌ | MEDIUM | Placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRespectBorders | ❌ | LOW | Respecter bordures |
| SetRole | ❌ | LOW | Rôle |
| SetScaleFlag | ❌ | LOW | Flag échelle |
| SetTag | ❌ | LOW | Tag |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiComplexForm (31 méthodes) - Formulaires complexes
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Add | ❌ | MEDIUM | Ajouter sous-formulaire |
| Clear | ❌ | MEDIUM | Effacer |
| ClearContent | ❌ | MEDIUM | Effacer contenu |
| Copy | ❌ | LOW | Copier |
| Delete | ❌ | MEDIUM | Supprimer |
| GetClassType | ❌ | LOW | Type classe |
| GetFormKey | ❌ | MEDIUM | Obtenir clé |
| GetFormType | ❌ | LOW | Type |
| GetInternalId | ❌ | LOW | ID interne |
| GetPlaceholderText | ❌ | LOW | Placeholder |
| GetRole | ❌ | LOW | Rôle |
| GetSubForms | ❌ | MEDIUM | Sous-formulaires |
| GetTag | ❌ | LOW | Tag |
| GetText | ❌ | LOW | Texte |
| GetTextPr | ❌ | LOW | Propriétés texte |
| GetTipText | ❌ | LOW | Info-bulle |
| GetWrapperShape | ❌ | LOW | Forme conteneur |
| IsFixed | ❌ | LOW | Est fixe |
| IsRequired | ❌ | LOW | Est requis |
| MoveCursorOutside | ❌ | LOW | Déplacer curseur |
| SetBackgroundColor | ❌ | MEDIUM | Couleur fond |
| SetBorderColor | ❌ | MEDIUM | Couleur bordure |
| SetFormKey | ❌ | MEDIUM | Définir clé |
| SetPlaceholderText | ❌ | MEDIUM | Placeholder |
| SetRequired | ❌ | HIGH | Définir requis |
| SetRole | ❌ | LOW | Rôle |
| SetTag | ❌ | LOW | Tag |
| SetTextPr | ❌ | LOW | Propriétés texte |
| SetTipText | ❌ | LOW | Info-bulle |
| ToFixed | ❌ | LOW | Convertir fixe |
| ToInline | ❌ | LOW | Convertir inline |

### ApiFormRoles (9 méthodes) - Gestion des rôles
| Méthode | Implémenté | Priorité | Notes |
|---------|------------|----------|-------|
| Add | ❌ | LOW | Ajouter rôle |
| GetAllRoles | ❌ | LOW | Tous les rôles |
| GetCount | ❌ | LOW | Nombre rôles |
| GetRoleColor | ❌ | LOW | Couleur rôle |
| HaveRole | ❌ | LOW | A le rôle |
| MoveDown | ❌ | LOW | Déplacer bas |
| MoveUp | ❌ | LOW | Déplacer haut |
| Remove | ❌ | LOW | Supprimer rôle |
| SetRoleColor | ❌ | LOW | Définir couleur |

---

## Fonctionnalités implémentées (27)

| Outil MCP | Méthode API | Classe |
|-----------|-------------|--------|
| `pdf_annotation_add` | - | (raccourci clavier) |
| `pdf_page_count` | - | (via doc_info) |
| `pdf_goto_page` | - | (raccourci clavier) |
| `pdf_forms_get_all` | GetAllForms | ApiDocument |
| `pdf_forms_get_data` | GetFormsData | ApiDocument |
| `pdf_form_get_value` | GetFormValueByKey | ApiDocument |
| `pdf_forms_set_data` | SetFormsData | ApiDocument |
| `pdf_form_set_text` | SetText | ApiTextForm |
| `pdf_form_set_checkbox` | SetChecked | ApiCheckBoxForm |
| `pdf_form_select_option` | SelectListValue | ApiComboBoxForm |
| `pdf_get_info` | - | (via doc_info) |
| `pdf_role_add` | Add | ApiFormRoles |
| `pdf_role_remove` | Remove | ApiFormRoles |
| `pdf_roles_list` | GetAllRoles | ApiFormRoles |
| `pdf_role_count` | GetCount | ApiFormRoles |
| `pdf_role_set_color` | SetRoleColor | ApiFormRoles |
| `pdf_role_get_color` | GetRoleColor | ApiFormRoles |
| `pdf_form_set_bg_color` | SetBackgroundColor | ApiFormBase |
| `pdf_form_set_border_color` | SetBorderColor | ApiFormBase |
| `pdf_form_get_text` | GetText | ApiFormBase |
| `pdf_forms_get_by_key` | GetFormsByKey | ApiDocument |
| `pdf_forms_clear_all` | ClearAllFields | ApiDocument |
| `pdf_form_get_date` | GetDate | ApiDateForm |
| `pdf_form_date_set_format` | SetFormat | ApiDateForm |
| `pdf_form_date_get_format` | GetFormat | ApiDateForm |
| `pdf_form_picture_get_image` | GetImage | ApiPictureForm |
| `pdf_form_combo_get_list` | GetListValues | ApiComboBoxForm |

---

## Priorités pour v1.1

### HIGH - Création de formulaires
| Méthode | Classe | Nouvel outil |
|---------|--------|--------------|
| CreateTextForm | Api | `pdf_form_create_text` |
| CreateCheckBoxForm | Api | `pdf_form_create_checkbox` |
| CreateComboBoxForm | Api | `pdf_form_create_combobox` |
| InsertTextForm | ApiDocument | `pdf_form_insert_text` |
| SetRequired | ApiFormBase | `pdf_form_set_required` |

### HIGH - Manipulation de formulaires
| Méthode | Classe | Nouvel outil |
|---------|--------|--------------|
| SetDate | ApiDateForm | `pdf_form_set_date` |
| SetImage | ApiPictureForm | `pdf_form_set_image` |
| SetListValues | ApiComboBoxForm | `pdf_form_set_list_values` |
| Delete | ApiFormBase | `pdf_form_delete` |

### MEDIUM - Lecture de formulaires
| Méthode | Classe | Nouvel outil |
|---------|--------|--------------|
| GetFormsByKey | ApiDocument | `pdf_forms_get_by_key` |
| GetFormsByTag | ApiDocument | `pdf_forms_get_by_tag` |
| GetListValues | ApiComboBoxForm | `pdf_form_get_list_values` |
| GetDate | ApiDateForm | `pdf_form_get_date` |
| IsChecked | ApiCheckBoxForm | `pdf_form_is_checked` |

### MEDIUM - Personnalisation
| Méthode | Classe | Nouvel outil |
|---------|--------|--------------|
| SetBackgroundColor | ApiFormBase | `pdf_form_set_bg_color` |
| SetBorderColor | ApiFormBase | `pdf_form_set_border_color` |
| SetPlaceholderText | ApiFormBase | `pdf_form_set_placeholder` |
| ClearAllFields | ApiDocument | `pdf_forms_clear_all` |

---

## Statistiques finales

| Priorité | Méthodes | À implémenter |
|----------|----------|---------------|
| HIGH | 18 | 9 |
| MEDIUM | 52 | 9 |
| LOW | 199 | - |
| **Total** | **269** | **18** (v1.1) |
