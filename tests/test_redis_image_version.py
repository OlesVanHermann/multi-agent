from pathlib import Path


BASE = Path(__file__).resolve().parents[1]
IMAGE = "redis:8-alpine"


def test_redis_image_is_consistent():
    """Un bus recréé avec une image plus ancienne que celle qui a écrit son
    volume ne redémarre pas : Redis 7.4 refuse le format RDB 15 de Redis 8.10."""
    for relative in (
        "scripts/infra.sh",
        "setup/install_redis.sh",
        "setup/REDIS.md",
        "README.md",
        "framework/CHROME-BRIDGE.md",
    ):
        content = (BASE / relative).read_text()
        assert IMAGE in content, f"{relative} does not use {IMAGE}"
        assert "redis:7-alpine" not in content, f"{relative} still uses redis:7-alpine"
