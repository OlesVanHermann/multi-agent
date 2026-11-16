"""MA_UPGRADE_KEEP_LOCAL=1 : la synchronisation framework n'efface pas les
fichiers propres au site rangés sous les répertoires framework.

Constat mx81 (2026-11-13) : ~6800 fichiers de projet sous scripts/, utilisés
par des agents en cours, auraient disparu pendant toute la durée de l'upgrade
avec le `rsync --delete` des répertoires framework.
"""
import os
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
UPGRADE = BASE / "patch" / "upgrade.sh"


def sync_delete_count(env_value):
    src = UPGRADE.read_text()
    block = re.search(r"^SYNC_DELETE=\(--delete\)\n.*?SYNC_DELETE=\(\)\n",
                      src, re.M | re.S).group(0)
    env = {k: v for k, v in os.environ.items() if k != "MA_UPGRADE_KEEP_LOCAL"}
    if env_value is not None:
        env["MA_UPGRADE_KEEP_LOCAL"] = env_value
    r = subprocess.run(["bash", "-c", block + 'echo "${#SYNC_DELETE[@]}"'],
                       capture_output=True, text=True, env=env, check=True)
    return int(r.stdout.strip())


def test_delete_stays_the_default():
    assert sync_delete_count(None) == 1
    assert sync_delete_count("0") == 1


def test_keep_local_drops_delete():
    assert sync_delete_count("1") == 0


def test_framework_sync_and_dry_run_count_use_the_switch():
    lines = [line for line in UPGRADE.read_text().splitlines()
             if "--exclude='secrets.cfg'" in line
             and '"$TEMP_DIR/$dir/" "./$dir/"' in line]
    assert len(lines) == 2, lines
    for line in lines:
        assert '"${SYNC_DELETE[@]}"' in line
        assert "--delete" not in line
