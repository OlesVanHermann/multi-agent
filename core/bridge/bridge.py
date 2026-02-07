#!/usr/bin/env python3
"""
Bridge - Syncs Redis between Mac and VM via SSH tunnel

Opens SSH tunnel to VM Redis, then syncs streams bidirectionally.
Handles disconnection and catchup.

Runs on Mac only - VM just needs Redis on 127.0.0.1:6379
"""

import os
import sys
import json
import time
import asyncio
import subprocess
import signal
from datetime import datetime
from typing import Optional, Dict, Set
from dataclasses import dataclass
import logging

try:
    import redis.asyncio as aioredis
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "redis", "-q"])
    import redis.asyncio as aioredis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [BRIDGE] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

MA_PREFIX = os.environ.get("MA_PREFIX", "ma")

# Streams to sync
SYNC_STREAMS = [
    f"{MA_PREFIX}:tasks:global",      # Super-Master → Master
    f"{MA_PREFIX}:results:global",    # Results back
    f"{MA_PREFIX}:heartbeat",         # Health
]


@dataclass
class BridgeConfig:
    local_redis: str = "redis://127.0.0.1:6379"
    ssh_host: str = ""
    ssh_user: str = "ubuntu"
    ssh_port: int = 22
    ssh_key: str = ""
    remote_redis_port: int = 6379
    tunnel_local_port: int = 6380  # Local port for tunnel
    state_file: str = "/app/state/bridge.json"


class Bridge:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.local: Optional[aioredis.Redis] = None
        self.remote: Optional[aioredis.Redis] = None
        self.tunnel_process: Optional[subprocess.Popen] = None
        
        self.last_ids: Dict[str, str] = {}  # stream → last synced ID
        self.processed: Dict[str, Set[str]] = {}  # Dedup
        
        self._running = False
    
    async def start(self):
        """Start the bridge"""
        logger.info("Starting Bridge")
        logger.info(f"  Local Redis: {self.config.local_redis}")
        logger.info(f"  Remote: {self.config.ssh_user}@{self.config.ssh_host}")
        
        # Connect to local Redis
        self.local = aioredis.from_url(self.config.local_redis, decode_responses=True)
        await self.local.ping()
        logger.info("Local Redis: connected")
        
        # Load state
        self._load_state()
        
        # Initialize dedup sets
        for stream in SYNC_STREAMS:
            if stream not in self.processed:
                self.processed[stream] = set()
        
        self._running = True
        
        # Main loop with reconnection
        while self._running:
            try:
                # Open SSH tunnel
                if not await self._open_tunnel():
                    logger.warning("Tunnel failed, retrying in 5s...")
                    await asyncio.sleep(5)
                    continue
                
                # Connect to remote Redis via tunnel
                self.remote = aioredis.from_url(
                    f"redis://127.0.0.1:{self.config.tunnel_local_port}",
                    decode_responses=True,
                    socket_connect_timeout=5
                )
                await self.remote.ping()
                logger.info("Remote Redis: connected via tunnel")
                
                # Sync loop
                await self._sync_loop()
                
            except Exception as e:
                logger.error(f"Bridge error: {e}")
                await self._close_remote()
                await asyncio.sleep(5)
        
        await self.stop()
    
    async def stop(self):
        """Stop the bridge"""
        logger.info("Stopping Bridge")
        self._running = False
        self._save_state()
        await self._close_remote()
        if self.local:
            await self.local.close()
    
    async def _open_tunnel(self) -> bool:
        """Open SSH tunnel to VM Redis"""
        if self.tunnel_process and self.tunnel_process.poll() is None:
            return True  # Already running
        
        cmd = [
            "ssh", "-N", "-L",
            f"{self.config.tunnel_local_port}:127.0.0.1:{self.config.remote_redis_port}",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ExitOnForwardFailure=yes",
            "-p", str(self.config.ssh_port),
        ]
        
        if self.config.ssh_key:
            cmd.extend(["-i", self.config.ssh_key])
        
        cmd.append(f"{self.config.ssh_user}@{self.config.ssh_host}")
        
        logger.info(f"Opening SSH tunnel...")
        
        try:
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for tunnel to establish
            await asyncio.sleep(2)
            
            if self.tunnel_process.poll() is not None:
                logger.error("SSH tunnel failed to start")
                return False
            
            logger.info(f"SSH tunnel open on 127.0.0.1:{self.config.tunnel_local_port}")
            return True
            
        except Exception as e:
            logger.error(f"SSH error: {e}")
            return False
    
    async def _close_remote(self):
        """Close remote connection and tunnel"""
        if self.remote:
            try:
                await self.remote.close()
            except:
                pass
            self.remote = None
        
        if self.tunnel_process:
            self.tunnel_process.terminate()
            self.tunnel_process = None
    
    async def _sync_loop(self):
        """Main sync loop"""
        logger.info("Starting sync loop")
        
        while self._running:
            try:
                # Check tunnel health
                if self.tunnel_process and self.tunnel_process.poll() is not None:
                    logger.warning("Tunnel died")
                    return
                
                # Sync each stream both ways
                for stream in SYNC_STREAMS:
                    # Local → Remote
                    await self._sync_stream(stream, self.local, self.remote, "→")
                    # Remote → Local
                    await self._sync_stream(stream, self.remote, self.local, "←")
                
                # Small delay between sync cycles
                await asyncio.sleep(0.1)
                
            except aioredis.ConnectionError:
                logger.warning("Connection lost")
                return
            except Exception as e:
                logger.error(f"Sync error: {e}")
                await asyncio.sleep(1)
    
    async def _sync_stream(self, stream: str, source, dest, direction: str):
        """Sync messages from source to dest"""
        try:
            last_id = self.last_ids.get(f"{stream}:{direction}", '0')
            
            # Read new messages
            messages = await source.xrange(stream, min=f"({last_id}", count=100)
            
            if not messages:
                return
            
            synced = 0
            for msg_id, data in messages:
                # Dedup
                key = f"{stream}:{msg_id}"
                if key in self.processed[stream]:
                    continue
                
                # Skip if originated from other side (prevent loops)
                if data.get('_bridge') == direction:
                    continue
                
                try:
                    # Mark origin
                    data['_bridge'] = "←" if direction == "→" else "→"
                    data['_bridge_time'] = datetime.utcnow().isoformat()
                    
                    # Write to dest
                    await dest.xadd(stream, data, maxlen=10000)
                    
                    self.processed[stream].add(key)
                    synced += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to sync {msg_id}: {e}")
                    break
            
            if synced > 0:
                self.last_ids[f"{stream}:{direction}"] = messages[-1][0]
                logger.debug(f"Synced {synced} messages {direction} on {stream}")
                
                # Trim dedup set
                if len(self.processed[stream]) > 10000:
                    self.processed[stream] = set(list(self.processed[stream])[-5000:])
                
        except Exception as e:
            logger.debug(f"Stream {stream} sync error: {e}")
    
    def _save_state(self):
        """Save sync state"""
        try:
            os.makedirs(os.path.dirname(self.config.state_file), exist_ok=True)
            with open(self.config.state_file, 'w') as f:
                json.dump({
                    "last_ids": self.last_ids,
                    "saved_at": datetime.utcnow().isoformat()
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
    
    def _load_state(self):
        """Load sync state"""
        try:
            with open(self.config.state_file, 'r') as f:
                state = json.load(f)
                self.last_ids = state.get("last_ids", {})
                logger.info(f"Loaded state from {self.config.state_file}")
        except FileNotFoundError:
            logger.info("No previous state")
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")


async def main():
    config = BridgeConfig(
        local_redis=os.environ.get('LOCAL_REDIS', 'redis://127.0.0.1:6379'),
        ssh_host=os.environ.get('SSH_HOST', ''),
        ssh_user=os.environ.get('SSH_USER', 'ubuntu'),
        ssh_port=int(os.environ.get('SSH_PORT', 22)),
        ssh_key=os.environ.get('SSH_KEY', '/root/.ssh/id_rsa'),
        remote_redis_port=int(os.environ.get('REMOTE_REDIS_PORT', 6379)),
        tunnel_local_port=int(os.environ.get('TUNNEL_LOCAL_PORT', 6380)),
        state_file=os.environ.get('STATE_FILE', '/app/state/bridge.json'),
    )
    
    if not config.ssh_host:
        logger.error("SSH_HOST not set")
        sys.exit(1)
    
    bridge = Bridge(config)
    
    # Handle shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))
    
    await bridge.start()


if __name__ == "__main__":
    asyncio.run(main())
