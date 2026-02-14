# Frontend Monitoring

Documentation pour surveiller la stabilité du dashboard web.

---

## Script de test : test-frontend-stability.sh

**Emplacement** : `scripts/test-frontend-stability.sh`

**Rôle** : Surveille le frontend pendant 2 heures pour détecter les problèmes de stabilité (crashes, timeouts, processus zombies).

### Usage

```bash
# Lancer le test en arrière-plan
nohup ./scripts/test-frontend-stability.sh > /dev/null 2>&1 &

# Ou directement
./scripts/test-frontend-stability.sh
```

### Ce que ça teste

Le script effectue **24 vérifications** (toutes les 5 minutes pendant 2 heures) :

1. **HTTP GET** : Le frontend répond à `http://127.0.0.1:8000`
2. **API** : L'endpoint `/api/agents` fonctionne
3. **Response time** : Temps de réponse en secondes
4. **Process** : Le processus uvicorn tourne

### Logs

Les résultats sont enregistrés dans :
```
logs/000/frontend-stability-YYYYMMDD_HHMMSS.log
```

**Exemple de log** :
```
=== Frontend Stability Test ===
Start: sam. 14 févr. 2026 12:54:08 CET
Duration: 2 hours (24 checks, every 5 min)

[Check 1/24] 12:54:08
  ✓ HTTP GET OK
  ✓ API OK
  ⏱ Response time: 0.002707s
  ✓ Process running

[Check 2/24] 12:59:08
  ✓ HTTP GET OK
  ✓ API OK
  ⏱ Response time: 0.003012s
  ✓ Process running

...

=== Test Complete ===
End: sam. 14 févr. 2026 14:54:08 CET
Log: /path/to/log
```

### Interpréter les résultats

**✓ Tous les checks passent** → Frontend stable

**✗ HTTP GET FAILED** → Frontend inaccessible (probable crash ou timeout)

**✗ Process NOT running** → Uvicorn s'est arrêté

**Response time > 1s** → Ralentissement, possibles problèmes

### Bugs connus fixés (v2.4.1)

1. **Compaction reload loop** : Le backend envoyait "deviens agent..." en boucle après compaction
   - Fix : Flag Redis `reload_sent` pour ne déclencher qu'une seule fois

2. **Zombie processes** : Plusieurs processus uvicorn tournaient en même temps
   - Fix : Amélioration de `scripts/web.sh` avec force kill

3. **WebSocket crashes** : Le frontend crashait après 10-15 minutes
   - Fix : Ajout de `ClientDisconnected` aux exception handlers dans `server.py`

4. **Frontend non compilé** : Erreur si `web/frontend/dist/` manquant
   - Fix : `./scripts/web.sh rebuild` recompile le frontend

### Dépannage

**Frontend ne répond pas** :
```bash
# Vérifier si uvicorn tourne
pgrep -f "uvicorn server:app"

# Vérifier les logs
tail -50 ~/multi-agent/logs/000/dashboard.log

# Redémarrer
./scripts/web.sh rebuild
```

**Frontend compilé ?** :
```bash
ls -la web/frontend/dist/index.html
# Si manquant → ./scripts/web.sh rebuild
```

---

## Monitoring continu

Pour une surveillance 24/7, utiliser `scripts/monitor.py` qui surveille tous les agents + le frontend.

```bash
python3 scripts/monitor.py
```

---

*Documentation v2.4.1 - Février 2026*
