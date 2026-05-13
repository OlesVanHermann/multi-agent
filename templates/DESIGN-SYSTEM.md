# Design System - Rapports d'Analyse

**Basé sur :** IONOS Site Builder Specifications v1.0
**Usage :** Tous les rapports générés par les agents 3XX et 390

---

## 1. Structure du Document

### Hiérarchie 3 niveaux

```markdown
# PARTIE 1 : HIGH LEVEL - Vue Stratégique
## 1.1 Section principale
### 1.1.1 Sous-section

# PARTIE 2 : MID LEVEL - Analyse Détaillée
## 2.1 Section principale

# PARTIE 3 : LOW LEVEL - Données Techniques
## 3.1 Section principale
```

### En-tête de rapport

```markdown
# Rapport d'Analyse - [ENTREPRISE]

**Date :** YYYY-MM-DD
**Version :** X.X
**Agents :** 323, 336, 347, 354, 374, 390
```

---

## 2. Palette de Couleurs

| Couleur | Code Hex | Usage |
|---------|----------|-------|
| Bleu primaire | `#003D8F` | Titres, headers tableaux |
| Orange accent | `#F5A623` | CTA, alertes, scores élevés |
| Vert succès | `#28A745` | Points forts, validations ✅ |
| Rouge erreur | `#DC3545` | Points faibles, alertes ❌ |
| Jaune warning | `#FFC107` | Avertissements ⚠️ |
| Gris texte | `#333333` | Texte principal |
| Gris secondaire | `#6C757D` | Labels, texte secondaire |

---

## 3. Typographie

### Titres

| Niveau | Markdown | Usage |
|--------|----------|-------|
| H1 | `#` | Titre du rapport, Parties principales |
| H2 | `##` | Sections (1.1, 2.1, etc.) |
| H3 | `###` | Sous-sections (1.1.1, etc.) |
| H4 | `####` | Détails, sous-catégories |

### Corps de texte

- **Gras** : Termes importants, labels
- *Italique* : Citations, noms de produits
- `Code` : Valeurs techniques, URLs, commandes

---

## 4. Listes

### Puces standard

```markdown
▸ Point principal
▸ Autre point
  - Sous-point (tiret)
  - Autre sous-point
```

### Listes de statuts

```markdown
✅ Élément validé / Point fort
❌ Élément manquant / Point faible
⚠️ Attention requise
➡️ Action recommandée
↑ Tendance hausse
↓ Tendance baisse
→ Stable
```

---

## 5. Tableaux

### Standard (données)

```markdown
| Métrique | Valeur | Tendance |
|----------|--------|----------|
| Score SEO | 7.5/10 | ↑ |
| Trafic | 1.2M | → |
```

### Comparatif

```markdown
| Critère | Entreprise | Concurrent A | Concurrent B |
|---------|------------|--------------|--------------|
| Prix | 9.99€ | 12.99€ | 8.99€ |
```

### Scores

```markdown
| Domaine | Score | Appréciation |
|---------|-------|--------------|
| SEO Technique | 8/10 | ✅ Excellent |
| Performance | 6/10 | ⚠️ Moyen |
| Réputation | 4/10 | ❌ Faible |
```

---

## 6. Encadrés et Notes

### Information

```markdown
> **ℹ️ Note :** Information complémentaire importante.
```

### Avertissement

```markdown
> **⚠️ Attention :** Point de vigilance à surveiller.
```

### Alerte critique

```markdown
> **🚨 ALERTE :** Problème critique nécessitant action immédiate.
```

### Astuce / Recommandation

```markdown
> **💡 Recommandation :** Action suggérée pour amélioration.
```

---

## 7. Scores et Métriques

### Format des scores

```markdown
## Score Global

| Domaine | Score |
|---------|-------|
| SEO Technique | 8/10 |
| Réputation | 7/10 |
| Performance | 6/10 |
| Entreprise | 7/10 |
| SEO/SEM | 8/10 |
| **TOTAL** | **36/50** |
```

### Indicateurs visuels

| Plage | Indicateur | Signification |
|-------|------------|---------------|
| 8-10 | ✅ | Excellent |
| 6-7 | 🔶 | Bon / Acceptable |
| 4-5 | ⚠️ | Moyen / À améliorer |
| 0-3 | ❌ | Faible / Critique |

### Tendances

| Symbole | Signification |
|---------|---------------|
| ↑ | Hausse significative |
| ↗ | Légère hausse |
| → | Stable |
| ↘ | Légère baisse |
| ↓ | Baisse significative |

---

## 8. Sections Spéciales

### Executive Summary

```markdown
## Executive Summary

▸ **Point clé 1** : Description courte
▸ **Point clé 2** : Description courte
▸ **Point clé 3** : Description courte

**Score global : X/50** | **Recommandation : [Action principale]**
```

### Alertes Critiques

```markdown
## 🚨 Alertes Critiques

| Type | Description | Urgence |
|------|-------------|---------|
| Prix | Hausse de 15% détectée | Haute |
| Infra | Nouveau datacenter EU | Moyenne |
```

### Recommandations

```markdown
## Recommandations

### Priorité Haute
1. **[Action]** - Impact attendu

### Priorité Moyenne
2. **[Action]** - Impact attendu

### Priorité Basse
3. **[Action]** - Impact attendu
```

---

## 9. Pied de Rapport

```markdown
---

*Rapport généré automatiquement le [DATE]*
*Agents : 323, 336, 347, 354, 374 → 390*
*Multi-Agent System v2.3*
```

---

## 10. Exemples Complets

### Tableau de synthèse SEO

| Critère | Valeur | Score | Status |
|---------|--------|-------|--------|
| Meta Title | Présent (58 car.) | 9/10 | ✅ |
| Meta Description | Présent (142 car.) | 8/10 | ✅ |
| H1 | 1 unique | 10/10 | ✅ |
| Images Alt | 85% renseignés | 7/10 | 🔶 |
| HTTPS | Actif | 10/10 | ✅ |
| Mobile-Friendly | Oui | 10/10 | ✅ |

### Tableau réputation

| Source | Note | Avis | Tendance |
|--------|------|------|----------|
| Trustpilot | 4.2/5 | 12,450 | ↗ |
| Google | 4.5/5 | 3,200 | → |
| Reddit | Mitigé | - | ↘ |

### Bloc métriques clés

```
┌─────────────────────────────────────────────────┐
│  MÉTRIQUES CLÉS                                 │
├─────────────────────────────────────────────────┤
│  Trafic mensuel    │  1.2M visites    │  ↑ +5% │
│  Part organique    │  68%             │  → 0%  │
│  Bounce rate       │  42%             │  ↘ -2% │
│  Temps moyen       │  3m 24s          │  ↑ +8% │
└─────────────────────────────────────────────────┘
```

---

*Design System v1.0 - Janvier 2026*
*Source : IONOS Site Builder Specifications*
