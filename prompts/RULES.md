# RÈGLES OBLIGATOIRES POUR TOUS LES AGENTS

## 0. PRINCIPE FONDAMENTAL

```
1 AGENT = 1 TÂCHE = 1 LIVRABLE
```

Chaque agent :
- Reçoit **une seule tâche** à la fois
- Produit **exactement un fichier de sortie**
- Place ce fichier dans le répertoire correspondant à son domaine

Pas de multi-tâche. Pas de fichiers multiples dispersés. Un agent = un livrable clair.

---

## 1. AUTONOMIE 24/7

**Les agents travaillent en continu jusqu'à ce que le job soit TERMINÉ.**

- ❌ NE JAMAIS demander "Tu veux que je continue ?"
- ❌ NE JAMAIS attendre une confirmation pour continuer
- ❌ NE JAMAIS s'arrêter en milieu de tâche
- ✅ TOUJOURS continuer automatiquement jusqu'à completion
- ✅ TOUJOURS relancer si erreur (retry 3x avant d'escalader)

## 2. RAPPORTS AU MASTER (100)

**Après CHAQUE tâche, envoyer un rapport COMPLET au Master:**

```bash
redis-cli RPUSH "ma:inject:100" "FROM:{MON_ID}|DONE {ENTREPRISE} - {RÉSUMÉ COMPLET}"
```

Le rapport DOIT contenir:
- ✅ Status: SUCCESS / FAILED / PARTIAL
- ✅ Fichiers créés (liste complète avec chemins)
- ✅ Stats (nombre de pages, taille, durée)
- ✅ Erreurs rencontrées (si applicable)
- ✅ Prochaine action recommandée

**Exemple de rapport CORRECT:**
```
FROM:300|DONE scaleway.com - SUCCESS
Crawl terminé: 479 pages HTML
Fichiers: studies/scaleway.com/300/html/*.html (479 fichiers, 125MB)
Durée: 2h15m
Erreurs: 3 timeouts (retry OK)
Prochaine étape: Agent 306 peut extraire
```

**Exemple de rapport INCORRECT:**
```
FROM:300|Crawl en cours...
```
(Pas assez d'info pour que 100 décide)

## 3. GESTION DES ERREURS

1. **Erreur temporaire** (timeout, rate limit): Retry 3x avec backoff
2. **Erreur permanente** (fichier manquant, permission): Rapport immédiat à 100
3. **Blocage** (besoin input humain): Rapport à 100 avec `BLOCKED: raison`

## 4. FORMAT DES MESSAGES INTER-AGENTS

```
FROM:{AGENT_ID}|{TYPE} {ENTREPRISE} - {DETAILS}
```

Types:
- `DONE` - Tâche terminée avec succès
- `FAILED` - Échec après retries
- `BLOCKED` - Besoin intervention
- `PROGRESS` - Update intermédiaire (pour tâches longues >30min)

## 5. STRUCTURE DES LIVRABLES

Chaque agent crée ses fichiers dans:
```
studies/{ENTREPRISE}/{AGENT_ID}/
```

Et documente dans un fichier `_manifest.json`:
```json
{
  "agent": 300,
  "entreprise": "scaleway.com",
  "status": "complete",
  "files": ["html/abc123.html", "..."],
  "stats": {"pages": 479, "size_mb": 125},
  "completed_at": "2024-01-30T22:30:00Z"
}
```

## 6. CHAÎNE DE RESPONSABILITÉ

```
100 (Master) dispatch → 3XX execute → rapport à 100 → 100 dispatch suivant
```

Le Master 100:
- Reçoit les rapports de TOUS les agents
- Décide de la prochaine étape
- Dispatch au prochain agent
- Track la progression globale

## 7. JAMAIS D'INTERRUPTION

Si un agent doit faire une tâche longue (crawl, analyse):
1. Lancer en background si possible
2. Envoyer `PROGRESS` toutes les 30 minutes
3. Envoyer `DONE` quand terminé
4. NE JAMAIS demander confirmation pour continuer
