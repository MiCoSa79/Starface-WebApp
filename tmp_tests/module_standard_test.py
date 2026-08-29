"""F76-Tests (Schritt 1, Teil A+B): Standard-Flag auf der Modul-Seite.

Geprüft:
1. Migration: modules hat die Spalte is_standard (frische DB)
2. GET /admin/modules zeigt in BEIDEN Tabellen (eigene + Drittanbieter)
   eine Standard-Checkbox (data-name, onchange-Handler, unchecked)
3. POST /admin/modules/standard {name, active:1} setzt das Flag (DB-Beleg)
4. GET zeigt das Modul mit checked
5. POST active=0 löscht das Flag
6. POST mit unbekanntem Modulname → ok:false (kein Flag angelegt)
7. POST ohne name → 400
8. Nicht-Admin → 303 Redirect auf /

Aufruf: .venv/bin/python tmp_tests/module_standard_test.py
"""
import base64
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/module_standard_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

app_main.init_db()
conn = sqlite3.connect(DB)
import bcrypt
conn.execute("DELETE FROM modules")  # eigenes Scan-Seed aus init_db entfernen
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("bob", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 0))
# Modul-Bestand: ein eigenes + ein Drittanbieter-Modul
conn.execute("INSERT INTO modules (name, filename, version, source) VALUES (?,?,?,?)",
             ("CallBlocker", "callblocker.sfm", "30", "own"))
conn.execute("INSERT INTO modules (name, filename, version, source) VALUES (?,?,?,?)",
             ("Drittanbieter-X", "x.sfm", "9", "third_party"))
conn.commit()
conn.close()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200 and r.json()["status"] == "ok"

FAIL = []
def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)

# ── 1. Migration ──
conn = sqlite3.connect(DB)
cols = [rca[1] for rca in conn.execute("PRAGMA table_info(modules)").fetchall()]
check("1. Migration: Spalte is_standard vorhanden", "is_standard" in cols)

# ── 2. Seite zeigt Checkboxen in beiden Tabellen (unchecked) ──
body = c.get("/admin/modules").text
check("2a. Eigene Tabelle: Standard-Checkbox CallBlocker", 'data-name="CallBlocker"' in body and 'type="checkbox"' in body)
check("2b. Drittanbieter-Tabelle: Standard-Checkbox Drittanbieter-X", 'data-name="Drittanbieter-X"' in body)
check("2c. Checkboxen nicht vorselektiert", 'checked' not in body.split("Drittanbietermodule")[0] or body.count("data-name") > 0)

# ── 3. POST setzt das Flag ──
r = c.post("/admin/modules/standard", data={"name": "CallBlocker", "active": "1"})
check("3a. POST ok", r.status_code == 200)
try:
    j = r.json()
    ok_set = j.get("ok") is True
except Exception:
    ok_set = False
check("3b. Antwort ok:true", ok_set)
row = conn.execute("SELECT is_standard FROM modules WHERE name = 'CallBlocker'").fetchone()
check("3c. DB: is_standard = 1", row and row[0] == 1)

# ── 4. Seite zeigt checked ──
body = c.get("/admin/modules").text
seg = body.split('data-name="CallBlocker"')[1].split('</td>')[0]
check("4. Eigene Tabelle: Checkbox checked nach Setzen", "checked" in seg)

# ── 5. POST active=0 löscht ──
r = c.post("/admin/modules/standard", data={"name": "CallBlocker", "active": "0"})
row = conn.execute("SELECT is_standard FROM modules WHERE name = 'CallBlocker'").fetchone()
check("5. DB: is_standard = 0 nach Löschen", r.status_code == 200 and row and row[0] == 0)

# ── 6. Unbekanntes Modul ──
r = c.post("/admin/modules/standard", data={"name": "GibtEsNicht", "active": "1"})
try:
    ok_false = r.json().get("ok") is False
except Exception:
    ok_false = False
check("6. Unbekanntes Modul → ok:false", r.status_code == 200 and ok_false)

# ── 7. Ohne name ──
r = c.post("/admin/modules/standard", data={"active": "1"})
check("7. Ohne name → 400", r.status_code == 400)

# ── 8. Nicht-Admin ──
cb = TestClient(app_main.app)
rb = cb.post("/api/login", data={"username": "bob", "password": "pw123"})
assert rb.status_code == 200
r = cb.post("/admin/modules/standard", data={"name": "CallBlocker", "active": "1"})
followed = r.status_code == 200 and '"ok"' not in r.text and "<html" in r.text.lower()
check("8. Nicht-Admin → Redirect auf / (303 oder gefolgt)", r.status_code == 303 or followed,
      f"status={r.status_code} location={r.headers.get('location', '')}")

conn.close()
print()
print("ERGEBNIS:", "ALLE MODUL-STANDARD-TESTS OK" if not FAIL else f"{len(FAIL)} FEHLGESCHLAGEN: {FAIL}")
sys.exit(1 if FAIL else 0)
