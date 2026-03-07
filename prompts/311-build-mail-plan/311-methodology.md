# 311 — Methodology (mono)

## Process de developpement

### Phase 0 : Lire le contexte
1. Lire 311-memory.md (tache courante, comportements a tester)
2. Lire spec.md / CHANGES.md de la tache dans plan-DONE
3. Identifier le nom du fichier : `test_{Cat}_{num}_{name}.py`

### Phase 1 : Curer les sources
1. Lire CHANGES.md de la tache (ce qui a ete implemente)
2. Lire les fichiers .rs produits (fonctions cles)
3. Lire la spec fonctionnelle
4. Mettre a jour 311-memory.md avec les infos pertinentes (budget 2000 tokens)

### Phase 2 : Ecrire le script de test
1. Structure : docstring + imports + config + fixtures + classes Test*
2. Min 8 tests : happy path + edge cases + error handling + RFC compliance
3. Assertions reelles sur status, contenu, structure
4. Skip gracieux si serveur indisponible
5. finally s.close() sur tout socket raw

### Phase 3 : Auto-verifier (checklist gate)
1. Verifier la checklist gate de 311-system.md
2. Score auto-evalue sur les 5 criteres ponderes
3. Ecrire bilan dans bilans/311-cycle{N}.md
4. Si score < 98% : corriger et re-verifier (max 6 iterations)

**Gate couverture exhaustive (a faire avant Phase 3) :**
- Extraire la liste complete des structs/methodes/fonctions de 311-memory.md section 2
- Pour chaque item : verifier qu'il existe un `test_*` qui le teste explicitement
- Items a risque eleve : structs de type Inbound* (ex: InboundItip), methodes booléennes (ex: expects_reply), fonctions utilitaires de conversion (ex: epoch_to_ical)
- Manque = ajouter le test avant de passer a la Phase 4 — ne pas supposer que l'item est couvert par un test generique

### Phase 4 : Finaliser
1. Copier test vers /home/ubuntu/imap-next-gen/tests/
2. Creer entree plan-DONE-TEST
3. Signaler completion via Redis
4. Enchainer tache suivante

## Patterns par categorie

### A — Structure (tests fichiers/dirs)
```python
import os
def test_file_exists():
    assert os.path.exists(path), f"Missing: {path}"
```

### B — Database (PostgreSQL)
```python
import asyncpg
@pytest.fixture
async def db():
    conn = await asyncpg.connect("postgresql://localhost:15432/stalwart_test")
    yield conn
    await conn.close()
```

### C — Redis
```python
import redis
@pytest.fixture
def redis_conn():
    r = redis.Redis(host="localhost", port=16379, decode_responses=True)
    try: r.ping(); yield r
    except redis.ConnectionError: pytest.skip("Redis not available")
```

### D/E/F — PIM (commandes IMAP custom)
```python
def test_pim_capability(imap_tls):
    status, caps = imap_tls.capability()
    assert status == "OK"
```

## Regles apprises (historique corrections)
- Prefix `test_` OBLIGATOIRE (pytest discovery)
- CHANGES.md dedie par feature (pas reutiliser)
- CAPABILITY tagged (pas juste banner)
- IMAP4REV2 OR IMAP4REV1 (pas AND)
- Chaque classe protocole : 1 test commande inconnue
- finally s.close() sur tout socket raw
- Tests de contenu (pas seulement existence)
- Tester les cas d'erreur API : JSON corrompu, reponse vide, status != 200 :
  ```python
  def test_invalid_json_response(self, monkeypatch):
      import json
      def bad_get(*a, **kw):
          class R:
              status_code = 200
              def json(self): raise json.JSONDecodeError("bad", "", 0)
          return R()
      monkeypatch.setattr("requests.get", bad_get)
      with pytest.raises((json.JSONDecodeError, ValueError, KeyError)):
          parse_response(bad_get())
  ```

## Changelog
- v1 : methodology triangle x45
- v2 : mono agent (tout-en-un)
- v3 : cycle3 score 98/100, C4=97 — ajout pattern test erreur JSON corrompu (chirurgical)
- v4 : cycle5 score 97 — gate couverture exhaustive : InboundItip/expects_reply/epoch_to_ical manquants → checklist struct-par-struct obligatoire avant Phase 4
