# 100-500 — Methodology

## Étapes
1. Lire les logs de dispatch de 100
2. Vérifier l'ordre de démarrage des agents
3. Évaluer chaque métrique (0-100%) :
   - Séquencement : bon ordre respecté
   - Timing : pas de blocages > 10 min
   - Complétude : tous les agents exécutés
   - Progression : pipeline avance
4. Calculer le score global
5. Lister les problèmes avec exemples
6. Écrire dans `bilans/100-cycle{N}.md`
7. Publier `bilans:ready` sur Redis
