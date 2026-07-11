"""
Durées de session Keycloak (web/keycloak/realm-multi-agent.json)

Contrat : l'opérateur ne doit pas se re-logger plusieurs fois par jour.
- idle >= 7 jours : le refresh token survit à un week-end sans ouvrir
  le dashboard (le frontend refresh au mount/réveil, AuthProvider.jsx) ;
- max >= idle : borne absolue cohérente ;
- access token court (<= 1 h) : la sécurité repose sur le refresh
  transparent, pas sur un access token longue durée.
"""
import json
import os

_REALM_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                           '..', 'web', 'keycloak', 'realm-multi-agent.json')


def _realm():
    with open(_REALM_FILE, encoding='utf-8') as f:
        return json.load(f)


def test_sso_idle_au_moins_7_jours():
    assert _realm()['ssoSessionIdleTimeout'] >= 7 * 86400


def test_sso_max_au_moins_l_idle():
    realm = _realm()
    assert realm['ssoSessionMaxLifespan'] >= realm['ssoSessionIdleTimeout']


def test_access_token_reste_court():
    assert _realm()['accessTokenLifespan'] <= 3600
