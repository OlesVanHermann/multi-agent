"""
Triangle auto-resolve par vivacité (resolve_triangle_target, scripts/lib.sh)

Règle partagée send.sh / done.sh. Depuis un émetteur en triangle (NNN-XXX),
une cible nue YYY est résolue en NNN-YYY seulement si la cible triangle
tourne, ou si rien ne tourne (inbox rejouée au redémarrage). Si seule la
cible nue tourne (plan global, ex. Master 100), elle est conservée : les
signaux d'un triangle vers le plan global ne partent plus en orphan queue.
"""
import os
import shutil
import subprocess

import pytest

_HERE = os.path.dirname(os.path.realpath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, '..'))
_LIB = os.path.join(_REPO, 'scripts', 'lib.sh')

pytestmark = pytest.mark.skipif(shutil.which('tmux') is None, reason='tmux absent')


def _resolve(from_agent, to_agent, prefix):
    out = subprocess.run(
        ['bash', '-c', f'source "{_LIB}"; resolve_triangle_target "$1" "$2" test',
         '_', from_agent, to_agent, prefix],
        capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.fixture
def tmux_prefix():
    """Fabrique de sessions tmux canoniques jetables."""
    prefix = f'RT{os.getpid() % 10000}'
    created = []

    def make(agent_id):
        name = f'agent-{agent_id}'
        # Depuis v3.1.17 les tests et la production partagent les noms
        # canoniques (plus de MA_PREFIX). Une session opérateur peut donc déjà
        # exister : l'utiliser pour le test de vivacité, sans la tuer au teardown.
        exists = subprocess.run(
            ['tmux', 'has-session', '-t', f'={name}'],
            capture_output=True).returncode == 0
        if exists:
            return name
        subprocess.run(['tmux', 'new-session', '-d', '-s', name], check=True)
        created.append(name)
        return name

    yield prefix, make
    for name in created:
        subprocess.run(['tmux', 'kill-session', '-t', f'={name}'], capture_output=True)


class TestTriangleResolve:
    def test_cible_triangle_vivante_resolue(self, tmux_prefix):
        prefix, make = tmux_prefix
        make('399-500')
        assert _resolve('399-199', '500', prefix) == '399-500'

    def test_plan_global_vivant_conserve(self, tmux_prefix):
        """Le cas rapporté : 399-199 signale au Master global 100."""
        prefix, make = tmux_prefix
        make('100')  # 100 global tourne, 399-100 n'existe pas
        assert _resolve('399-199', '100', prefix) == '100'

    def test_triangle_prioritaire_si_les_deux_vivants(self, tmux_prefix):
        """Raccourci intra-triangle préservé même si un homonyme global tourne."""
        prefix, make = tmux_prefix
        make('100')
        make('300-100')
        assert _resolve('300-500', '100', prefix) == '300-100'

    def test_rien_ne_tourne_resolution_historique(self, tmux_prefix):
        """Aucune session : résolu vers le triangle (inbox rejouée au restart)."""
        prefix, _ = tmux_prefix
        assert _resolve('399-199', '100', prefix) == '399-100'

    def test_correspondance_tmux_exacte(self, tmux_prefix):
        """=name : la session 399-100 ne doit pas répondre pour la cible 10."""
        prefix, make = tmux_prefix
        make('399-100')
        make('10')
        assert _resolve('399-199', '10', prefix) == '10'

    def test_emetteur_hors_triangle_inchange(self, tmux_prefix):
        prefix, _ = tmux_prefix
        assert _resolve('cli', '100', prefix) == '100'
        assert _resolve('300', '100', prefix) == '100'

    def test_cible_composee_inchangee(self, tmux_prefix):
        prefix, _ = tmux_prefix
        assert _resolve('399-199', '300-100', prefix) == '300-100'
