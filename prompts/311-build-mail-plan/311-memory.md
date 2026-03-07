# 311 — Memory (cure par 311-711, cycle 1)

## Tache courante
- **Categorie** : D-pim-calendar
- **Tache** : 003-vevent-crud
- **Source** : /home/ubuntu/imap-next-gen/plan-DONE/D-pim-calendar/003-vevent-crud-output
- **Fichier de test** : `test_D_003_vevent_crud.py`

---

## 1. Ce qui a ete implemente

7 fichiers Rust :

| Fichier | Description |
|---------|-------------|
| `d003-append-vevent.rs` | `VEventData`, `VEventData::from_vevent()`, `vevent_etag()`, `handle_append_calendar()`, `append_vevent()` |
| `d003-fetch-pim.rs` | `PimFetchAttributes` (15 bool fields), `PimFetchItem`, `handle_fetch_pim()`, `fetch_pim()` |
| `d003-replace-vevent.rs` | `PimReplaceArgs`, `handle_pim_replace()`, `replace_vevent()` avec ETag conflict |
| `d003-patch-vevent.rs` | `PatchOp`, `VEventField`, `apply_patch()`, `PimPatchArgs`, `handle_pim_patch()`, `patch_vevent()` |
| `d003-expunge-vevent.rs` | `handle_expunge_calendar()`, `expunge_pim_events()`, `pim_event_ids_with_keyword()` |
| `d003-store-flags.rs` | `PimFlag`, `PimStoreOperation`, `PimStoreFlagsArgs`, `apply_flag_operation()`, `sync_status_from_flags()` |
| `d003-tests.rs` | 40+ tests unitaires Rust |

---

## 2. Fonctions / commandes cles a tester

### VEventData (struct — 17 champs)
- `mailbox_id`, `uid`, `etag`, `summary`, `dtstart`, `dtend`, `location`, `rrule`, `status`, `class`, `attendees` (Vec), `organizer`, `valarms` (Vec), `categories` (Vec), `priority` (Option<u8>), `transp`, `keywords` (Vec)
- `from_vevent(comp, etag, mailbox_id)` → None si UID absent
- `vevent_etag(raw: &[u8]) -> String` → DefaultHasher → 16 hex chars

### PimFetchAttributes (struct — 15 bool fields)
- `all()` → tous les 15 champs a true
- `from_names(&["PIM.UID", "PIM.SUMMARY"])` → seulement ces champs a true
- `from_names(&["PIM.*"])` → equivalent a all()
- `any_requested()` → false si tous a false

### PimFetchItem::serialize()
- Format : `* N FETCH (PIM.FIELD "value" ...)\r\n`
- Listes : `PIM.ATTENDEES ("addr1" "addr2")`
- PIM.PRIORITY sans guillemets (numerique)

### VEventField (enum — 14 variants)
- `from_str(s)` → case-insensitive (to_ascii_uppercase): SUMMARY, DTSTART, DTEND, LOCATION, RRULE, STATUS, CLASS, ORGANIZER, TRANSP, PRIORITY, ATTENDEE, CATEGORIES, VALARMS, DESCRIPTION
- `is_list()` → true pour Attendee, Categories, Valarms

### PatchOp (enum) : Set{field,value}, Add{field,value}, Remove{field}

### apply_patch(data, op)
- Set scalaire → remplace
- Add liste (Attendee/Categories) → dedup (pas ajout si deja present)
- Add Valarms → toujours ajoute
- Remove liste → vide la liste
- Remove scalaire → None

### REPLACE : `PIM REPLACE <uid/seq> [(IF-MATCH "etag")] {size}\r\nical_data`
- Conflict : `NO [PIM-CONFLICT]` si etag mismatch
- Invalid : `BAD [PIM-INVALID-ICAL]`
- UID mismatch : `NO [CANNOT]`
- OK : `OK [ETAG "new_etag"] PIM REPLACE completed.`
- keywords preserves

### PATCH : `PIM PATCH <uid/seq> [(IF-MATCH "etag")] (ops...)`
- OK : `OK [ETAG "new_etag"] PIM PATCH completed.`
- ETag recalcule depuis uid+summary+dtstart+dtend+location+rrule+attendees.join(",")

### APPEND : `APPEND "CalendarName" {size}\r\nical_data`
- OK : `[APPENDUID uid_validity uids] [ETAG "etag"]`
- Erreur si UID absent : `[PIM-INVALID-ICAL]`

### EXPUNGE : `EXPUNGE` ou `UID EXPUNGE <seq>`
- Supprime PimEvent avec `\Deleted` keyword
- Filtre par mailbox_id

### PimFlag (enum) : Cancelled, Tentative, Confirmed, Draft, Private, Standard(Keyword)
- `from_keyword(kw)` → `\\PIM-Cancelled` ou `\\Pim-Cancelled` (deux formes)
- `as_keyword_str()` → `\\PIM-Cancelled`, etc.

### sync_status_from_flags(data)
- Priorite STATUS : Cancelled > Confirmed > Tentative > Draft > None (preserve existant)
- `\\PIM-Private` → class = "PRIVATE"
- Si PIM-Private retire et class etait PRIVATE → class = "PUBLIC"

### pim_event_ids_with_keyword()
- Utilise BitmapKey pour lookup keyword, filtre par mailbox_id

---

## 3. RFC de reference

| RFC | Role |
|-----|------|
| RFC 9051 (IMAP4rev2) | Base IMAP, APPEND, STORE, EXPUNGE |
| RFC 4791 (CalDAV) | Collections calendrier, ETag |
| RFC 5545 (iCalendar) | VEVENT, proprietes |

---

## 4. Assertions a tester

### VEventData (unit)
1. `vevent_etag(b"test")` → string de 16 hex chars
2. `vevent_etag(same_input)` == `vevent_etag(same_input)` (deterministe)
3. `vevent_etag(a)` != `vevent_etag(b)` pour inputs differents
4. `from_vevent` avec UID present → Some(VEventData)
5. `from_vevent` sans UID → None

### PimFetchAttributes (unit)
6. `all()` → 15 champs a true
7. `from_names(["PIM.UID", "PIM.SUMMARY"])` → uid=true, summary=true, dtstart=false
8. `from_names(["PIM.*"])` → tous a true
9. `from_names([])` → tous a false, `any_requested()` = false
10. `any_requested()` apres `all()` = true

### VEventField (unit)
11. `from_str("SUMMARY")` → Some(Summary)
12. `from_str("summary")` → Some(Summary) (case insensitive)
13. `from_str("DTSTART")` → Some(DtStart)
14. `from_str("ATTENDEE")` → Some(Attendee)
15. `from_str("UNKNOWN")` → None
16. `is_list(Attendee)` → true, `is_list(Summary)` → false

### apply_patch (unit)
17. Set Summary → summary = Some("value")
18. Add Attendee → attend list grows (no dup)
19. Add Attendee deja present → pas de doublon
20. Remove Attendees → liste vide
21. Remove scalaire → None
22. Add Valarms → toujours ajoute (meme si present)

### PimFetchItem::serialize() (unit)
23. Contient `* N FETCH (`
24. Liste attendees → `PIM.ATTENDEES ("addr1" "addr2")`
25. Priority sans guillemets : `PIM.PRIORITY 5`
26. Termine par `)\r\n`

### PimFlag (unit)
27. `from_keyword("\\PIM-Cancelled")` → Some(Cancelled)
28. `from_keyword("\\Pim-Confirmed")` → Some(Confirmed)
29. `from_keyword("\\Seen")` → None (non PIM)
30. `as_keyword_str(Tentative)` == `"\\PIM-Tentative"`

### sync_status_from_flags (unit)
31. keywords=[`\\PIM-Cancelled`] → status="CANCELLED"
32. keywords=[`\\PIM-Confirmed`] → status="CONFIRMED"
33. keywords=[`\\PIM-Cancelled`, `\\PIM-Confirmed`] → status="CANCELLED" (Cancelled > Confirmed)
34. keywords=[`\\PIM-Private`] → class="PRIVATE"
35. keywords=[] avec class="PRIVATE" → class="PUBLIC"
36. keywords=[] sans flag statut → status preservee

### IMAP integration (connexion TLS + ENABLE PIM)
37. `APPEND "TestCal" {size}\r\nvalid_ical` → OK + APPENDUID + ETAG
38. `APPEND "TestCal" {size}\r\nno_uid_ical` → BAD PIM-INVALID-ICAL
39. `PIM REPLACE <uid> (IF-MATCH "wrong") {size}\r\nical` → NO PIM-CONFLICT
40. `PIM REPLACE <uid> () {size}\r\nical` → OK ETAG (sans verification)
41. `PIM PATCH <uid> () (SET SUMMARY "New")` → OK ETAG
42. `STORE 1 +FLAGS (\\PIM-Confirmed)` → * 1 FETCH (FLAGS (\\PIM-Confirmed))
43. `STORE 1 FLAGS (\\Deleted)` puis `EXPUNGE` → * 1 EXPUNGE

---

## 5. Edge cases importants

- `vevent_etag("")` → 16 hex chars (pas d'erreur)
- `PimFetchAttributes::from_names(["PIM.UNKNOWN"])` → ignore, tous a false
- REPLACE avec UID different → CANNOT
- PATCH sans IF-MATCH → pas de verification conflict
- Add Attendee deja dans liste → pas de doublon
- Add Valarms (toujours ajoute, pas de dedup)
- sync_status_from_flags : si PIM-Private retire → PUBLIC (pas None)
- EXPUNGE sans \Deleted → OK sans expunge

---

## 6. Connexion et setup

```python
import imaplib, ssl, pytest

IMAP_HOST = "localhost"
IMAP_PORT = 993
TEST_USER = "test@example.com"
TEST_PASS = "testpassword"

@pytest.fixture
def imap_auth():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        s = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
    except (ConnectionRefusedError, OSError):
        pytest.skip("IMAP server not available")
    status, _ = s.login(TEST_USER, TEST_PASS)
    if status != "OK":
        pytest.skip("IMAP login failed")
    s.send(b"E001 ENABLE PIM\r\n")
    for _ in range(5):
        line = s.readline()
        if line.startswith(b"E001 "):
            break
    yield s
    try:
        s.logout()
    except Exception:
        pass

def _raw_pim(conn, subcmd, tag="P001"):
    conn.send(f"{tag} PIM {subcmd}\r\n".encode())
    lines = []
    for _ in range(20):
        line = conn.readline().decode(errors="replace")
        lines.append(line.strip())
        if line.startswith(f"{tag} "):
            break
    return lines
```

APPEND via raw socket :
```python
ical = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:test@ex\r\nSUMMARY:Test\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
conn.send(f"A001 APPEND TestCal {{len(ical)}}\r\n".encode())
conn.readline()  # continuation +
conn.send(ical)
# lire reponse tagged
```
