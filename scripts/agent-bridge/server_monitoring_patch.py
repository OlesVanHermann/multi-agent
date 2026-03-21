"""
server_monitoring_patch.py — Instructions d'intégration monitoring dans server.py
R-INTEGRATE : Montage create_monitoring_router dans web/backend/server.py
EF-008 : Extraction monitoring de server.py

Ce fichier montre les modifications exactes à appliquer dans server.py
pour intégrer le monitoring dashboard.

--- PATCH 1: Ajouter import (après les imports existants, ~L28) ---

    import redis as redis_sync  # sync client pour monitoring
    from monitoring.dashboard_api import create_monitoring_router

--- PATCH 2: Dans lifespan(), après redis_pool.ping() (~L365) ---

    # R-INTEGRATE: monitoring router (sync redis pour modules monitoring)
    sync_redis = redis_sync.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True
    )
    monitoring_router = create_monitoring_router(sync_redis, prefix="mi")
    app.include_router(monitoring_router)

--- PATCH 3: Dans lifespan() shutdown, avant redis_pool.close() (~L383) ---

    if sync_redis:
        sync_redis.close()

--- RÉSULTAT ---

Les endpoints suivants seront montés dans l'app FastAPI existante :
  GET  /api/monitoring/metrics              — Métriques de tous les agents
  GET  /api/monitoring/metrics/{agent_id}   — Métriques d'un agent
  GET  /api/monitoring/metrics/{agent_id}/latency — Historique latence
  GET  /api/monitoring/alerts               — Alertes actives
  POST /api/monitoring/alerts/{id}/ack      — Acquitter une alerte
  GET  /api/monitoring/summary              — Résumé agrégé
  POST /api/monitoring/check                — Lancer un check tous agents

Note: FastAPI exécute les handlers sync dans un thread pool,
donc le sync redis_client fonctionne correctement avec l'event loop async.
"""
