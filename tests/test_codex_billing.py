"""E1 — Facturation : le forfait ChatGPT, jamais l'API à l'usage.

Codex accepte deux modes d'authentification :

    « Sign in with ChatGPT »     → usage décompté sur l'abonnement
    « Provide your own API key » → facturation AU TOKEN

Trois façons de basculer **silencieusement** sur la facturation à l'usage :

    1. un `codex login` passé fait avec une clé API, encore en cache
    2. OPENAI_API_KEY présent dans l'environnement du shell
    3. CODEX_API_KEY idem

Sur un parc d'agents qui tournent en continu, ça se compte en centaines d'euros
avant qu'on s'en aperçoive. Et rien ne le signale : le CLI fonctionne, les
agents répondent, la facture arrive plus tard.

Trois verrous, testés ici :

    a. préflight     — refus de démarrer si le profil est authentifié par clé API
    b. lancement     — `-c forced_login_method=chatgpt`
    c. environnement — `env -u OPENAI_API_KEY -u CODEX_API_KEY`

Opt-in explicite pour assumer la facturation à l'usage : CODEX_ALLOW_API_KEY=1.

Libellés de `codex login status` :
[Documenté: openai/codex — codex-rs/cli/src/login.rs:440,449,456]
[Vérifié: codex-cli 0.144.1]
"""
import os
import shutil
import subprocess

import pytest


def _find_project_root(start, markers=('CLAUDE.md', '.git')):
    current = os.path.realpath(start)
    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, m)) for m in markers):
            return current
        current = os.path.dirname(current)
    raise FileNotFoundError(f"Marqueur {markers} introuvable depuis {start}")


BASE_DIR = _find_project_root(os.path.dirname(os.path.realpath(__file__)))
ENGINES_SH = os.path.join(BASE_DIR, 'scripts', 'engines.sh')

# Sorties réelles de `codex login status` (stderr).
STATUS_CHATGPT = 'Logged in using ChatGPT'
STATUS_API_KEY = 'Logged in using an API key - sk-***abcd'
STATUS_TOKEN = 'Logged in using access token'


def sh(snippet, env=None, check_rc=False):
    e = dict(os.environ)
    e.pop('OPENAI_API_KEY', None)
    e.pop('CODEX_API_KEY', None)
    e.pop('CODEX_ALLOW_API_KEY', None)
    if env:
        e.update(env)
    r = subprocess.run(['bash', '-c', f'source "{ENGINES_SH}"\n{snippet}'],
                       capture_output=True, text=True, timeout=20, env=e)
    if check_rc:
        assert r.returncode == 0, r.stderr
    return r


@pytest.fixture
def fake_codex(tmp_path):
    """Faux binaire `codex` : `login status` renvoie ce qu'on lui dit."""
    def make(status_line, rc=0):
        bin_dir = tmp_path / 'bin'
        bin_dir.mkdir(exist_ok=True)
        script = bin_dir / 'codex'
        script.write_text(
            "#!/bin/bash\n"
            'if [ "$1" = "login" ] && [ "$2" = "status" ]; then\n'
            f'  echo {status_line!r} >&2\n'
            f'  exit {rc}\n'
            'fi\n'
            'exit 0\n'
        )
        script.chmod(0o755)
        return str(bin_dir)
    return make


# ═══ VERROU a — préflight ═══

class TestPreflight:
    def test_api_key_login_is_refused(self, fake_codex, tmp_path):
        """LE test. Un login par clé API facture au token, hors forfait."""
        bin_dir = fake_codex(STATUS_API_KEY)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert r.returncode != 0
        assert 'CLÉ API' in r.stderr
        assert 'hors forfait' in r.stderr
        assert 'codex logout' in r.stderr, "le message doit dire QUOI faire"

    def test_chatgpt_login_is_accepted(self, fake_codex):
        bin_dir = fake_codex(STATUS_CHATGPT)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert r.returncode == 0, r.stderr

    def test_not_logged_in_is_refused(self, fake_codex):
        bin_dir = fake_codex('Not logged in', rc=1)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert r.returncode != 0
        assert 'non authentifié' in r.stderr

    def test_unknown_method_is_refused(self, fake_codex):
        """Ni ChatGPT ni clé API (ex. access token) → refus par défaut.
        Le doute ne doit jamais pencher du côté qui coûte de l'argent."""
        bin_dir = fake_codex(STATUS_TOKEN)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert r.returncode != 0

    def test_api_key_wording_is_checked_first(self, fake_codex):
        """Un diagnostic mixte mentionnant les deux ne doit pas être pris pour
        un login ChatGPT au seul motif qu'il contient le mot « ChatGPT »."""
        bin_dir = fake_codex('Logged in using an API key (ChatGPT plan inactive)')
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert r.returncode != 0

    def test_opt_in_allows_api_key(self, fake_codex):
        bin_dir = fake_codex(STATUS_API_KEY)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}",
                    'CODEX_ALLOW_API_KEY': '1'})
        assert r.returncode == 0, r.stderr

    def test_preflight_is_per_profile(self, fake_codex, tmp_path):
        """Chaque compte a son CODEX_HOME. Le préflight doit sonder CE profil,
        pas le ~/.codex global — sinon un profil non authentifié passerait."""
        bin_dir = tmp_path / 'bin2'
        bin_dir.mkdir()
        probe = tmp_path / 'probe.txt'
        (bin_dir / 'codex').write_text(
            "#!/bin/bash\n"
            f'echo "$CODEX_HOME" > {probe}\n'
            f'echo {STATUS_CHATGPT!r} >&2\n')
        (bin_dir / 'codex').chmod(0o755)
        sh('engine_codex_preflight /LOGINS codex3b',
           env={'PATH': f"{bin_dir}:{os.environ['PATH']}"})
        assert probe.read_text().strip() == '/LOGINS/codex3b'

    def test_missing_binary_is_refused(self):
        r = sh('engine_codex_preflight /L codex1a', env={'CODEX_BIN': 'codex-nope-xyz'})
        assert r.returncode != 0
        assert 'introuvable' in r.stderr

    def test_skip_login_check_escape_hatch(self, fake_codex):
        """Trousseau inaccessible (conteneur) : on peut sauter le préflight.
        Les verrous b et c, eux, tiennent toujours."""
        bin_dir = fake_codex(STATUS_API_KEY)
        r = sh('engine_codex_preflight /L codex1a',
               env={'PATH': f"{bin_dir}:{os.environ['PATH']}",
                    'CODEX_SKIP_LOGIN_CHECK': '1'})
        assert r.returncode == 0


# ═══ VERROU b — forced_login_method ═══

class TestForcedLoginMethod:
    def test_flag_present_by_default(self):
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol', check_rc=True).stdout
        assert '-c forced_login_method=chatgpt' in out

    def test_flag_absent_when_opted_in(self):
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol',
                 env={'CODEX_ALLOW_API_KEY': '1'}, check_rc=True).stdout
        assert 'forced_login_method' not in out

    def test_no_shell_quotes_to_escape(self):
        """La commande transite par `tmux send-keys` : une valeur guillemetée
        (`forced_login_method="chatgpt"`) serait fragile. Codex parse la valeur
        en TOML et retombe sur la chaîne brute — la forme nue suffit.
        [Vérifié: codex-cli 0.144.1]"""
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol', check_rc=True).stdout
        assert 'forced_login_method="' not in out
        assert "forced_login_method='" not in out


# ═══ VERROU c — environnement ═══

class TestEnvScrubbing:
    def test_api_keys_are_unset(self):
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol', check_rc=True).stdout
        assert out.startswith('env -u OPENAI_API_KEY -u CODEX_API_KEY ')

    def test_scrub_precedes_codex_home(self):
        """`env -u …` doit précéder l'affectation, sinon CODEX_HOME est perdu."""
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol', check_rc=True).stdout
        assert out.index('env -u') < out.index('CODEX_HOME=') < out.index(' codex ')

    def test_no_scrub_when_opted_in(self):
        out = sh('engine_launch_cmd codex /L codex1a gpt-5.6-sol',
                 env={'CODEX_ALLOW_API_KEY': '1'}, check_rc=True).stdout
        assert 'env -u' not in out

    def test_claude_command_untouched(self):
        """Aucun de ces verrous ne doit toucher le chemin claude."""
        out = sh('engine_launch_cmd claude /L claude1a claude-opus-4-8',
                 check_rc=True).stdout.strip()
        assert out == 'CLAUDE_CONFIG_DIR=/L/claude1a claude --dangerously-skip-permissions'


# ═══ Vérification contre le VRAI binaire ═══

CODEX_BIN = shutil.which('codex')


@pytest.mark.skipif(CODEX_BIN is None,
                    reason="codex CLI absent — `npm i -g @openai/codex` pour activer")
class TestAgainstRealBinary:
    """La commande qu'on construit doit être acceptée par le vrai parseur.
    Sans ça, on découvre l'erreur au premier démarrage d'agent, en production.

    Activer en CI : npm install -g @openai/codex
    """

    def _parse_check(self, cmd):
        """`--help` fait parser tous les arguments sans lancer le TUI."""
        r = subprocess.run(f'{cmd} --help', shell=True, capture_output=True,
                           text=True, timeout=30,
                           env={**os.environ, 'CODEX_HOME': '/tmp/codex-parse-check'})
        return r.returncode == 0

    def test_generated_command_parses(self):
        out = sh('engine_launch_cmd codex /tmp/L codex1a gpt-5.6-sol H',
                 check_rc=True).stdout.strip()
        assert self._parse_check(out), f"le vrai codex refuse : {out}"

    def test_generated_command_parses_with_opt_in(self):
        out = sh('engine_launch_cmd codex /tmp/L codex1a gpt-5.6-sol M',
                 env={'CODEX_ALLOW_API_KEY': '1'}, check_rc=True).stdout.strip()
        assert self._parse_check(out)

    @pytest.mark.parametrize('effort', ['L', 'M', 'H'])
    def test_every_effort_level_parses(self, effort):
        out = sh(f'engine_launch_cmd codex /tmp/L codex1a gpt-5.6-sol {effort}',
                 check_rc=True).stdout.strip()
        assert self._parse_check(out)

    def test_bypass_flag_exists_in_this_version(self):
        """`--yolo` n'existe PAS en 0.144.1 — seul le nom long est valide."""
        h = subprocess.run([CODEX_BIN, '--help'], capture_output=True, text=True).stdout
        assert '--dangerously-bypass-approvals-and-sandbox' in h

    def test_login_status_subcommand_exists(self):
        h = subprocess.run([CODEX_BIN, 'login', '--help'],
                           capture_output=True, text=True).stdout
        assert 'status' in h
