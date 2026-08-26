"""E2E-Tests für die Admin-Verdrahtung des Update-Servers (Task 3, Glue).

Geprüft werden:
1. GET /admin rendert das neue Feld module_update_base_url (Template ok)
2. POST /admin/settings speichert module_update_base_url in settings
3. _module_update_base(): Priorität Admin-Einstellung > Env MODULE_UPDATE_BASE_URL > ""
4. GET /admin/modules rendert den Spiegel-Status (aktiv bei versions.json, sonst Hinweis)

Aufruf: python3 tmp_tests/admin_settings_test.py
"""
import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_settings_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
for var in ("FERNET_KEY", "TOTP_ISSUER", "MODULE_UPDATE_BASE_URL"):
    os.environ.pop(var, None)

import main as app_main
from starlette.testclient import TestClient

app_main.init_db()
conn = sqlite3.connect(DB)
import bcrypt
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
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

# 1) Admin-Seite rendert neues Feld
r = c.get("/admin")
html = r.text
check("GET /admin -> 200", r.status_code == 200, str(r.status_code))
check("admin.html: Feld module_update_base_url vorhanden",
      'name="module_update_base_url"' in html and "modulupdates.meiser.family" in html)
btn_count = html.count('class="btn-primary">Speichern')
check("admin.html: jedes Feld mit eigenem Speichern-Button", btn_count == 2,
      str(btn_count) + " Button(s) gefunden")

# 2) POST speichert die Einstellung
# Starlette >=0.27 folgt Redirects automatisch (hartkodiert) → 303-POST endet
# bei GET /admin (200); der eigentliche Nachweis ist der gespeicherte Wert.
r = c.post("/admin/settings", data={"grafana_base_url": "", "module_update_base_url": "https://modulupdates.meiser.family"})
check("POST /admin/settings gespeichert (Redirect gefolgt)", r.status_code in (200, 303) and "/admin" in r.url.path, f"{r.status_code} {r.url}")
got = app_main._get_setting("module_update_base_url")
check("Einstellung gespeichert", got == "https://modulupdates.meiser.family", str(got))

# 2b) Teil-POSTs (je Feld ein eigenes Formular/Button) dürfen das jeweils
#     andere Feld NICHT überschreiben (None = nicht gepostet = unangetastet)
app_main._set_setting("grafana_base_url", "https://grafana.example")
r = c.post("/admin/settings", data={"module_update_base_url": "https://modulupdates.meiser.family"})
check("Teil-POST (nur Update-URL) lässt Grafana-URL unangetastet",
      app_main._get_setting("grafana_base_url") == "https://grafana.example",
      str(app_main._get_setting("grafana_base_url")))
r = c.post("/admin/settings", data={"grafana_base_url": "https://grafana.example"})
check("Teil-POST (nur Grafana-URL) lässt Update-URL unangetastet",
      app_main._get_setting("module_update_base_url") == "https://modulupdates.meiser.family",
      str(app_main._get_setting("module_update_base_url")))

# 3) Priorität: Einstellung > Env > leer
os.environ["MODULE_UPDATE_BASE_URL"] = "https://env.example"
check("Priorität: Einstellung gewinnt über Env",
      app_main._module_update_base() == "https://modulupdates.meiser.family")
app_main._set_setting("module_update_base_url", "")
check("Fallback: Env, wenn Einstellung leer",
      app_main._module_update_base() == "https://env.example")
os.environ.pop("MODULE_UPDATE_BASE_URL", None)
check("leer, wenn beides fehlt", app_main._module_update_base() == "")

# 4) /admin/modules: Spiegel-Status (versions.json liegt im html-ROOT,
#    NICHT in modules/ — Pfad-Fix b34e94d / v0.0.160)
modroot = os.path.dirname(DB)  # entspricht <data> = html-Root des nginx
os.makedirs(modroot, exist_ok=True)
r = c.get("/admin/modules")
check("GET /admin/modules -> 200 (ohne Spiegel)", r.status_code == 200, str(r.status_code))
check("Hinweis ohne versions.json", "nicht aktiv" in r.text)
with open(os.path.join(modroot, "versions.json"), "w") as fh:
    json.dump({"modules": [{"moduleName": "Fake", "versions": []}]}, fh)
r = c.get("/admin/modules")
check("GET /admin/modules -> 200 (mit Spiegel)", r.status_code == 200, str(r.status_code))
check("Badge aktiv bei versions.json (html-Root)", "Spiegel aktiv" in r.text and "1 Paket(e)" in r.text)
shutil.rmtree(modroot, ignore_errors=True)

print()
print("ERGEBNIS:", f"{len(FAIL)} FAIL" if FAIL else "ALLE ADMIN-SETTINGS-TESTS OK")
import sys
sys.exit(1 if FAIL else 0)
