#!/usr/bin/env python3
"""E2E-Test für den neuen Ändern-Button (blocklist/update) der Starface-WebApp.

Startet einen Fake-XML-RPC-Server (simuliert das CallBlocker-Modul auf der
Anlage) + die App über FastAPI TestClient und prüft den kompletten
Ändern-Fluss inkl. Fehlerfällen (Bestätigung 0 bei Add/Remove).
"""
import os
import re
import sqlite3
import sys
import tempfile
from urllib.parse import unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))
sys.path.insert(0, os.path.join(REPO, "tmp_tests"))

# ── Env VOR dem Import von main.py ────────────────────────────────
_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_test_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet  # noqa: E402
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "testpass123"
os.environ["APP_VERSION"] = "v0.0.73-test"

import main  # noqa: E402
from fake_starface import FAKE, start_fake  # noqa: E402

FAKE_URL = start_fake()

ok = 0


def check(label, cond, detail=""):
    global ok
    if cond:
        ok += 1
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        sys.exit(1)


from fastapi.testclient import TestClient  # noqa: E402

with TestClient(main.app) as c:
    # 1) Login
    r = c.post("/api/login", data={"username": "admin", "password": "testpass123"})
    j = r.json()
    check("Login", j.get("status") == "ok", str(j))
    check("Session-Cookie", bool(c.cookies.get("sf_webapp_session")))

    # 2) Installation anlegen (URL = Fake-Server)
    r = c.post("/admin/installations", data={
        "name": "Testanlage",
        "url": FAKE_URL,
        "auth_id": "rest-client-headless",
        "auth_pass": "x",
        "client_secret": "y",
        "module_instance_name": "CallBlocker",
        "is_starface10": 1,
    }, follow_redirects=False)
    check("Installation angelegt", r.status_code in (200, 303), f"status={r.status_code}")
    dash = c.get("/anlagen").text
    m = re.search(r"/installation/(\d+)/blocklist", dash)
    check("Instanz-ID gefunden", bool(m))
    inst_id = int(m.group(1))

    # 3) Blocklist leer
    r = c.get(f"/installation/{inst_id}/blocklist")
    check("3a) Seite rendert", r.status_code == 200, f"status={r.status_code}")
    check("3b) leere Liste", "Liste ist leer" in r.text)
    check("3c) keine Fehlerbox", 'class="msg-err' not in r.text,
          (re.search(r'class="msg-err[^>]*">(.*?)</div>', r.text, re.S) or type("m", (), {"group": lambda s, *a: "?"})()).group(1).strip() if 'class="msg-err' in r.text else "")

    # 4) Zwei Nummern hinzufügen
    r = c.post(f"/installation/{inst_id}/blocklist/add",
               data={"numbers": "123\n456"}, follow_redirects=False)
    check("4) Add ok=2", "ok=2" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.get(f"/installation/{inst_id}/blocklist")
    check("4b) beide in Seite", r.text.count('class="num"') == 2)
    check("4c) Ändern-Buttons vorhanden", r.text.count(">Ändern<") == 2)

    # 5) Ändern: 123 -> 789
    r = c.post(f"/installation/{inst_id}/blocklist/update",
               data={"old_number": "123", "new_number": "789"}, follow_redirects=False)
    check("5) Update leitet ok", "ok=1" in r.headers.get("location", ""), r.headers.get("location", ""))
    r = c.get(f"/installation/{inst_id}/blocklist")
    check("5b) neue Nummer sichtbar", ">789<" in r.text)
    check("5c) alte Nummer weg", ">123<" not in r.text)
    check("5d) Fake-Liste korrekt", sorted(FAKE["list"]) == ["456", "789"], str(FAKE["list"]))

    # 6) Ändern auf denselben Wert -> kein RPC
    before = len(FAKE["calls"])
    r = c.post(f"/installation/{inst_id}/blocklist/update",
               data={"old_number": "789", "new_number": "789"}, follow_redirects=False)
    check("6) Gleicher Wert ok ohne RPC",
          "ok=1" in r.headers.get("location", "") and len(FAKE["calls"]) == before)

    # 7) Fehlerfall: STARFACE lehnt Add ab (Bestätigung 0) -> alter Eintrag bleibt
    FAKE["fail_add"] = True
    r = c.post(f"/installation/{inst_id}/blocklist/update",
               data={"old_number": "456", "new_number": "999"}, follow_redirects=False)
    loc = unquote(r.headers.get("location", ""))
    check("7a) Fehlermeldung neu nicht übernommen", "nicht übernommen" in loc, loc)
    check("7b) Liste unverändert", sorted(FAKE["list"]) == ["456", "789"], str(FAKE["list"]))
    FAKE["fail_add"] = False

    # 8) Fehlerfall: Remove lehnt ab -> neue Nummer drin, alte noch da
    FAKE["fail_remove"] = True
    r = c.post(f"/installation/{inst_id}/blocklist/update",
               data={"old_number": "456", "new_number": "111"}, follow_redirects=False)
    loc = unquote(r.headers.get("location", ""))
    check("8a) Fehlermeldung alte nicht entfernt", "entfernt werden" in loc, loc)
    check("8b) neue Nummer hinzugefügt", "111" in FAKE["list"], str(FAKE["list"]))
    check("8c) alte noch da", "456" in FAKE["list"], str(FAKE["list"]))
    FAKE["fail_remove"] = False

    # 9) RPC-Reihenfolge bei Update: ListAdd VOR ListRemove
    idx_add = [i for i, cc in enumerate(FAKE["calls"]) if cc["method"] == "ListAdd" and cc["num"] == "789"]
    idx_rm = [i for i, cc in enumerate(FAKE["calls"]) if cc["method"] == "ListRemove" and cc["num"] == "123"]
    check("9) Add vor Remove", idx_add and idx_rm and idx_add[0] < idx_rm[0], str((idx_add, idx_rm)))

    # 10) Events protokolliert
    conn = sqlite3.connect(_tmpdb)
    rows = conn.execute("SELECT action, detail FROM events WHERE action='blocklist_update'").fetchall()
    conn.close()
    check("10) Update-Events geloggt", len(rows) >= 1 and any("123 -> 789" in d for _, d in rows), str(rows))

    # 11) Ohne Login kein Update
    c.cookies.clear()
    r = c.post(f"/installation/{inst_id}/blocklist/update",
               data={"old_number": "789", "new_number": "000"}, follow_redirects=False)
    check("11) Ohne Login kein Update",
          r.status_code in (303, 307) and r.headers.get("location", "").rstrip("/") == "",
          f"status={r.status_code} loc={r.headers.get('location','')}")

print(f"\nALLES GRÜN — {ok} Checks bestanden")
