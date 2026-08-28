"""F45-Tests: Seitenbreite (max-width 1400px) + Aktion-Buttons nebeneinander.

Geprüft (nach Axels Anforderung "Nutze mehr von der Breite des Bildschirms"
+ Screenshot Modul-Updates: Buttons rutschen untereinander):
1. Inhaltseiten rendern `.container { max-width: 1400px; ... }` (war 900/960/1100/720 je Template)
2. Modul-Updates + Modul-Seite: Aktion-Zellen `flex-wrap: nowrap` (Desktop), `wrap` nur <=640px
3. Login-Seite (password.html) bleibt bewusst schmal (max-width: 520px)

Aufruf: python3 tmp_tests/admin_layout_width_test.py
"""
import base64
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_layout_width_test/test.db"
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
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("axel", bcrypt.hashpw(b"pw456", bcrypt.gensalt()).decode(), 0))
conn.commit()
conn.close()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "pw123"})
assert r.status_code == 200 and r.json()["status"] == "ok"

passed, failed = [], []


def check(name, cond, detail=""):
    if cond:
        passed.append(name)
    else:
        failed.append((name, detail))


# Seiten, die auf 1400px breit sein muessen (Kandidaten: nur 200er wurden geprueft)
WIDE = ["/admin/updates", "/admin/modules", "/benutzer", "/monitoring",
        "/grundeinstellungen", "/wiki", "/"]
for route in WIDE:
    r = c.get(route)
    if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
        check(f"GET {route} rendert HTML (200)", False, f"status={r.status_code}")
        continue
    html = r.text
    check(f"GET {route} Container 1400px",
          "max-width: 1400px" in html,
          "CSS max-width: 1400px fehlt im Template")
    check(f"GET {route} kein altes Schmalklassen-Limit",
          all(x not in html for x in ("max-width: 900px", "max-width: 960px",
                                      "max-width: 1100px", "max-width: 720px")),
          "veraltete max-width-Breite noch im Template")

# Login (password.html) bleibt schmal — jetzt nur noch im Admin-Reset-Modus
# (GET /password ohne uid redirectet seit dem Menü-Umbau auf /konto#sicherheit)
for route in ("/login",):
    r = c.get(route)
    if r.status_code == 200:
        check("Login-Seite Container 520px", "max-width: 520px" in r.text)
        break
r = c.get("/password", params={"uid": "2"})  # Admin-Reset für Fremduser (uid 2)
check("Admin-Reset password.html Container 520px",
      r.status_code == 200 and "max-width: 520px" in r.text,
      f"status={r.status_code}")
r = c.get("/konto")
check("Mein-Konto /konto Container 1400px",
      r.status_code == 200 and "max-width: 1400px" in r.text,
      f"status={r.status_code}")

# Aktion-Buttons: Desktop nowrap, Mobil wrap (nur Modul-Tabellen)
for route in ("/admin/updates", "/admin/modules"):
    r = c.get(route)
    check(f"GET {route} Buttons nowrap (Desktop)",
          "flex-wrap: nowrap" in r.text and "td form" in r.text,
          "td form / flex-wrap: nowrap fehlt")
    check(f"GET {route} Buttons wrap (<=640px)",
          "@media (max-width: 640px)" in r.text and "flex-wrap: wrap" in r.text,
          "Media-Query wrap fehlt")

if failed:
    print(f"FEHLGESCHLAGEN ({len(failed)}):")
    for name, detail in failed:
        print(f"  - {name}: {detail}")
    sys.exit(1)
print(f"ALLE {len(passed)} CHECKS OK ({len(passed)} Layout-Vertraege verankert)")
