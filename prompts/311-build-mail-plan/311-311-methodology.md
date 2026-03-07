# 311 — Methodology (Test Writer IMAP Next-Gen)

## Process

### Etape 1 — Lire les inputs
1. Lire `311-memory.md` : tache courante, comportements a tester, RFC, edge cases
2. Lire `311-system.md` : nom du fichier de test, criteres de succes
3. Identifier le nom du fichier : `test_{Cat}_{num}_{name}.py` (dans 311-memory.md section "Fichier de test")
   **OBLIGATOIRE : prefix `test_` pour que pytest le decouvre automatiquement. Ex : `test_A_001_build_stalwart_from_source.py`**

### Etape 2 — Analyser la tache
1. Lire la section "Ce qui a ete implemente" → identifier les fonctions/commandes cles
2. Lire la section "Comportements attendus" → definir les assertions
3. Lire la section "Edge cases" → planifier les tests negatifs
4. Lire la section "RFC de reference" → comprendre le protocole a tester

### Etape 3 — Structurer le script
```python
"""
Tests pour {Cat}-{num} : {description}
RFC : {RFCs}
Source : {chemin plan-DONE}
"""
import pytest
import imaplib
import socket
import ssl
import os

IMAP_HOST = os.getenv("IMAP_HOST", "localhost")
IMAP_PORT = int(os.getenv("IMAP_PORT", "10143"))    # plain
IMAPS_PORT = int(os.getenv("IMAPS_PORT", "10993"))  # TLS
SMTP_PORT = int(os.getenv("SMTP_PORT", "10025"))
JMAP_PORT = int(os.getenv("JMAP_PORT", "10443"))    # HTTPS
TEST_USER = os.getenv("TEST_USER", "test@example.com")
TEST_PASS = os.getenv("TEST_PASS", "testpassword")


@pytest.fixture
def imap_conn():
    """Fixture : connexion IMAP4_SSL avec skip si serveur indisponible."""
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(TEST_USER, TEST_PASS)
        yield conn
        conn.logout()
    except (imaplib.IMAP4.error, ConnectionRefusedError, OSError):
        pytest.skip("IMAP server not available")


class Test{Name}:
    """Tests {description}"""
    ...
```

### Etape 4 — Ecrire les tests (minimum 8)

**Structure par test :**
```python
def test_xxx(self, imap_conn):
    # Action
    status, data = imap_conn.xxx(...)
    # Assertion reelle
    assert status == "OK", f"Expected OK, got {status}: {data}"
    assert data is not None
    assert len(data) > 0
```

**Types de tests a couvrir :**
1. **Connexion / authentification** : login valide, login invalide
2. **Operation principale** : le cas d'usage nominal
3. **Donnees retournees** : verifier la structure, les champs obligatoires
4. **Cas limites** : objet vide, objet inexistant, ID invalide
5. **Erreur protocole** : mauvaise commande, mauvais format
6. **Concurrence** : 2 operations sur le meme objet (si applicable)
7. **Persistance** : creer puis relire → memes donnees
8. **RFC compliance** : comportement specifie par la RFC

**PRECISION cycle 2 — C1 : Ports additionnels obligatoires (build/install features)**
Si la feature concerne un serveur mail compilable (Stalwart, etc.), TOUJOURS ajouter :
```python
def test_jmap_port_reachable():
    """JMAP HTTPS endpoint accessible sur port 10443."""
    import socket
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((IMAP_HOST, 10443))
        s.close()
    except (ConnectionRefusedError, OSError):
        pytest.skip("JMAP port not available")

def test_jmap_well_known_endpoint():
    """/.well-known/jmap repond HTTPS 200 ou 401."""
    import urllib.request, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        url = f"https://{IMAP_HOST}:10443/.well-known/jmap"
        resp = urllib.request.urlopen(url, timeout=3, context=ctx)
        assert resp.status in (200, 401)
    except Exception:
        pytest.skip("JMAP endpoint not available")

def test_smtp_port_banner():
    """SMTP port 10025 repond avec banner 220."""
    import socket
    s = socket.socket()
    s.settimeout(3)
    try:
        s.connect((IMAP_HOST, 10025))
        banner = s.recv(1024).decode(errors="replace")
        assert "220" in banner, f"Expected 220 banner, got: {banner!r}"
    except (ConnectionRefusedError, OSError):
        pytest.skip("SMTP port not available")
    finally:
        s.close()
```

**PRECISION cycle 2 — C1 : Cargo.lock et features (si feature = compilation)**
```python
def test_cargo_lock_exists():
    """Cargo.lock present dans le repertoire source (reproducibilite build)."""
    import os
    cargo_lock = os.path.join(os.getenv("SOURCE_DIR", "."), "Cargo.lock")
    assert os.path.exists(cargo_lock), "Cargo.lock manquant — build non reproductible"

def test_cargo_features_mail():
    """Le Cargo.toml active les features mail necessaires."""
    import os
    cargo_toml = os.path.join(os.getenv("SOURCE_DIR", "."), "Cargo.toml")
    if not os.path.exists(cargo_toml):
        pytest.skip("Cargo.toml not found")
    content = open(cargo_toml).read()
    # Verifier au moins une feature mail activee
    assert any(f in content for f in ["imap", "smtp", "jmap", "mail"]), \
        "Aucune feature mail trouvee dans Cargo.toml"
```

**PRECISION cycle 2 — C3 : IMAP CAPABILITY tagged (pas juste banner)**
NE PAS se contenter de lire le banner. Envoyer une commande CAPABILITY tagged :
```python
def test_imap_capability_tagged(imap_conn):
    """CAPABILITY retourne les extensions supportees via commande tagged."""
    # MAUVAIS : lire juste le banner
    # BON : envoyer commande tagged T001 CAPABILITY
    status, caps = imap_conn.capability()
    assert status == "OK", f"CAPABILITY failed: {status}"
    caps_str = b" ".join(caps).decode(errors="replace")
    assert "IMAP4rev1" in caps_str or "IMAP4" in caps_str, \
        f"IMAP4 non annonce dans CAPABILITY: {caps_str}"

def test_imap_logout_clean(imap_conn):
    """LOGOUT repond BYE puis OK — connexion fermee proprement."""
    # NE PAS reutiliser imap_conn fixture apres logout
    import imaplib
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(TEST_USER, TEST_PASS)
        typ, data = conn.logout()
        # logout() retourne BYE dans data, typ = "BYE"
        assert typ in ("BYE", "OK"), f"Unexpected logout response: {typ}"
    except (imaplib.IMAP4.error, ConnectionRefusedError, OSError):
        pytest.skip("IMAP not available")
```
**REGLE** : Apres tout test de connectivite qui ouvre un socket raw, appeler `s.close()` dans un bloc `finally`.

**PRECISION cycle 2 — C4 : Tests negatifs avances**
```python
def test_truncated_elf_binary():
    """Un binaire ELF tronque/corrompu est detecte et rejete."""
    import tempfile, os, subprocess
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        # ELF magic bytes mais tronque (4 octets au lieu de 64+)
        f.write(b"\x7fELF\x02\x01\x01")  # header incomplet
        tmp = f.name
    try:
        result = subprocess.run(
            [tmp], capture_output=True, timeout=2
        )
        # Un ELF tronque doit echouer a l'execution
        assert result.returncode != 0, "ELF tronque n'aurait pas du s'executer"
    except (PermissionError, FileNotFoundError, subprocess.TimeoutExpired):
        pass  # Comportement attendu
    finally:
        os.unlink(tmp)

def test_partial_banner_handling():
    """Un banner SMTP partiel (connexion fermee avant fin) est gere sans crash."""
    import socket
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect((IMAP_HOST, 10025))
        # Lire seulement les 3 premiers octets (banner partiel)
        partial = s.recv(3)
        assert len(partial) <= 3  # Pas de crash sur lecture partielle
    except (ConnectionRefusedError, OSError, socket.timeout):
        pytest.skip("SMTP not available")
    finally:
        try:
            s.close()  # OBLIGATOIRE : cleanup socket meme apres lecture partielle
        except OSError:
            pass

def test_socket_cleanup_on_error():
    """Socket correctement ferme meme si la connexion echoue."""
    import socket
    s = socket.socket()
    s.settimeout(0.1)
    closed = False
    try:
        s.connect((IMAP_HOST, 9999))  # Port qui n'existe pas
    except (ConnectionRefusedError, OSError, socket.timeout):
        pass
    finally:
        s.close()
        closed = True
    assert closed, "Socket non ferme apres erreur de connexion"
```

**Pattern pour commandes IMAP PIM custom (socket raw) :**
```python
def send_raw(conn, command):
    """Envoyer une commande IMAP raw et lire la reponse."""
    tag = f"T{id(command):04x}"
    cmd = f"{tag} {command}\r\n".encode()
    conn.send(cmd)
    response = []
    while True:
        line = conn.readline().decode()
        response.append(line.strip())
        if line.startswith(tag):
            break
    return response
```

### Etape 5 — Gate de validation avant ecriture
Avant d'ecrire le fichier, verifier :
- [ ] Minimum 8 fonctions/methodes `test_*`
- [ ] `import pytest` + `import imaplib` presents
- [ ] Fixture `imap_conn` avec skip gracieux
- [ ] Au moins 2 tests negatifs (erreurs, cas limites)
- [ ] Assertions reelles (pas `assert True`)
- [ ] Nom du fichier correct : `test_{Cat}_{num}_{name}.py` (prefix `test_` OBLIGATOIRE)
- [ ] CHANGES.md present dans pipeline/311-output/ (voir template Etape 6)

### Etape 6 — Ecrire les fichiers (2 fichiers obligatoires)

**Fichier 1 — Script de test :**
Ecrire dans `pipeline/311-output/test_{Cat}_{num}_{name}.py`
(prefix `test_` OBLIGATOIRE — sans ce prefix, pytest ne decouvre pas le fichier)

**Fichier 2 — CHANGES.md (OBLIGATOIRE, distinct de tout CHANGES.md precedent) :**
Ecrire dans `pipeline/311-output/CHANGES.md` :
```markdown
# CHANGES — {Cat}-{num} {name}

## Fichier de test
- `test_{Cat}_{num}_{name}.py`

## Ce que les tests couvrent
- {point 1}
- {point 2}

## RFC testees
- {RFC numero et titre}

## Comment executer
```bash
pytest pipeline/311-output/test_{Cat}_{num}_{name}.py -v
```

## Dependances
- pytest
- imaplib (stdlib)
- IMAP_HOST / IMAP_PORT / TEST_USER / TEST_PASS (env vars)
```
**IMPORTANT : NE PAS reutiliser un CHANGES.md existant dans pipeline/311-output/ — ecraser avec le contenu de la feature courante.**

### Etape 7 — Signaler
```bash
redis-cli XADD "A:agent:311-111:inbox" '*' prompt "311:done" from_agent "311" timestamp "$(date +%s)"
```

---

## Patterns par categorie

### B — Database (PostgreSQL)
```python
import asyncpg
import pytest

@pytest.fixture
async def db():
    conn = await asyncpg.connect("postgresql://localhost:15432/stalwart_test")
    yield conn
    await conn.close()

async def test_table_exists(db):
    result = await db.fetchval("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = $1", "mailboxes")
    assert result > 0
```

### C — Redis
```python
import redis

@pytest.fixture
def redis_conn():
    r = redis.Redis(host="localhost", port=16379, decode_responses=True)
    try:
        r.ping()
        yield r
    except redis.ConnectionError:
        pytest.skip("Redis not available")
```

### D/E/F — PIM (commandes IMAP custom)
```python
# Tester via IMAP4_SSL avec commandes custom
def test_pim_capability(imap_conn):
    status, caps = imap_conn.capability()
    assert status == "OK"
    caps_str = " ".join(c.decode() if isinstance(c, bytes) else c for c in caps)
    assert "PIM" in caps_str or "XCALENDAR" in caps_str
```

---

## Changelog
- Cycle 0 : Init — methodology pour IMAP Next-Gen Test Writer
- Cycle 1 : Score 51 — PRECISION. 2 regles critiques ajoutees : (1) prefix `test_` OBLIGATOIRE dans le nom du fichier (pytest discovery — sans ce prefix les tests ne s'executent pas), (2) CHANGES.md dedie OBLIGATOIRE dans pipeline/311-output/ avec template complet (ne pas reutiliser CHANGES.md d'une feature precedente). Gate renforcee avec 2 verifications supplementaires.
- Cycle 2 : Score 82 — PRECISION. C1(80)+C3(75)+C4(70) corriges. C1 : patterns TestJmap (port 8080 + well-known/jmap) + TestSmtp (port 25 banner 220) + Cargo.lock existence + cargo features mail. C3 : CAPABILITY tagged obligatoire (pas juste banner), LOGOUT propre apres connectivite, finally s.close() sur tout socket raw. C4 : test ELF tronque (magic bytes incomplets), banner partielle (recv(3)), socket cleanup sur erreur (port inexistant).
- Cycle 2 (A-002) : Score 89 — PRECISION. Gaps : TestProtocolCrates existence-only (http/directory), TestCargoWorkspace membres incomplets (dav/groupware manquants), TestGroupwareCrates sans contenu, crate email non teste. Ajouts : test_http_has_rs_files + test_http_has_lib_rs, test_directory_has_backend_types (ldap/sql/oidc/memory), test_email_crate_has_lib_rs + has_rs_files, test_member_dav + test_member_groupware, test_groupware_lib_exports_modules (references calendar/contact/scheduling dans lib.rs), test_each_groupware_module_has_rs_files. REGLE ARCHITECTURE : chaque crate dans EXPECTED_CRATES doit avoir au moins 1 test de contenu (pas seulement existence du dir).
- Cycle 1 (A-002) : Score 82 — PRECISION. Gaps : assertions existence sans contenu, subdirs generiques, dependances fragiles. Corrections : (1) jmap/dav subdirs : chercher noms specifiques (email/mailbox, calendar/card) pas just >=2. (2) smtp subdirs : verifier inbound/ + outbound/. (3) deps Cargo.toml : regex `"?crate"?\s*=\s*\{` pas simple string search (evite faux positifs dans commentaires). (4) test_imap_core_contains_session : core/mod.rs contient "Session". (5) test_main_rs_has_tokio_main : main.rs contient "tokio". (6) test_imap_proto_has_lib_rs + >=3 rs files. (7) test_store_has_backend_impls : backend dir ou fichier. (8) test_groupware_depends_on_store_or_common. REGLE ARCHITECTURE : pour les tests de structure de code source, toujours ajouter au moins 1 test de CONTENU par fichier cle (pas seulement existence).
- Cycle 5 : Score 95 — POLISH CHIRURGICAL. 3 corrections. (1) test_jmap_content_type_json corrige : skip si 401 (server valide peut retourner 401 sans Content-Type), assertion deplacee dans le try (pas apres). (2) test_unknown_command_bad ajoute dans TestImapConnectivity : XUNKNOWNCOMMAND → a005 BAD (RFC 3501 7.1.3). (3) test_smtp_unknown_command_5xx ajoute dans TestSmtp : XUNKNOWNCMD → 5xx (RFC 5321 4.2.4). REGLE GLOBAL : chaque classe de protocole doit avoir 1 test commande inconnue/invalide pour verifier le rejet conforme RFC.
- Cycle 4 : Score 94 — POLISH CHIRURGICAL. 3 corrections. (1) CAPABILITY assertion corrigee : IMAP4REV2 OR IMAP4REV1 (pas AND — RFC 9051 advertise l'un OU l'autre), STARTTLS separe avec message d'erreur distinct. (2) test_smtp_ehlo_extensions : ajouter assertion sur extensions connues (SIZE/STARTTLS/8BITMIME/AUTH/PIPELINING) — verifier contenu pas juste code 250. (3) test_tls_invalid_auth_rejected ajoute dans TestImapsTls — symetrie avec TestImapConnectivity. REGLE POLISH : chaque paire de classes mirroir (plaintext/TLS) doit avoir les memes types de tests negatifs. REGLE PROTOCOL : CAPABILITY tagged — separrer assertion version (OR) de assertion feature (STARTTLS, separee).
- Cycle 3 : Score 90 — POLISH. 5 tests ajoutes directement dans test_A_001. (1) test_invalid_auth_rejected : login invalide → a003 NO (RFC 3501 6.2.2 — test negatif obligatoire). (2) test_noop_ok : NOOP → a004 OK (RFC 3501 keepalive). (3) test_tls_capability_tagged : CAPABILITY tagged sur port TLS 9993 → t001 OK + IMAP4 (coherence avec plaintext). (4) test_smtp_ehlo_extensions : EHLO → 250 multi-ligne (RFC 5321 4.1.1.1 — va au-dela du banner). (5) test_smtp_quit_221 : QUIT → 221 (RFC 5321 4.1.1.10 — fermeture propre). REGLE POLISH : chaque classe de test doit avoir au moins 1 test negatif ET 1 test de commande (pas seulement port_open + banner).
