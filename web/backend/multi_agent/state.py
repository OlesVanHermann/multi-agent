"""État mutable partagé du dashboard (B1).

Toujours accéder via `state.xxx` (jamais `from .state import xxx`) pour que
les réaffectations (lifespan, tests) soient visibles partout.
"""

import asyncio
from typing import Optional

# Redis connection pool — set by the lifespan
redis_pool = None

# Background cache: all read endpoints serve from this, a background task refreshes it
_cache = {
    "agents": [],       # list of agent dicts
    "health": {"status": "starting", "redis": False, "timestamp": 0},
    "mode": "pipeline", # "pipeline" or "x45"
    "triangles": {},    # {worker_id: {worker, curator, coach}}
    "timestamp": 0,     # last refresh epoch
}
_cache_lock = asyncio.Lock()
_cache_task: Optional[asyncio.Task] = None

# Event logging: previous states for transition detection
_prev_agent_states: dict[str, dict] = {}
_prev_inbox_xlens: dict[str, int] = {}
