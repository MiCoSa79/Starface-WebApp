"""T4-Tests: Admin-UI 'Modul-Updates' (Phase 2 UpdateDeployer).

Geprüft:
1. Migration: installations hat deployer_instance_name + deployer_token
2. edit_installation speichert beide Felder (Token verschlüsselt, Roundtrip ok)
3. GET /admin/updates rendert Anlagen + SOLL-Module mit Update-Buttons
4. POST /admin/updates/push ruft push_update mit filename/version + Token
   und zeigt Erfolg; Fehlerfall zeigt die Meldung
5. Ungültige installation_id → sauberer Redirect (kein Crash)

Aufruf: python3 tmp_tests/admin_updates_test.py
"""
import base64
import json
import os
import sqlite3
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_updates_test/test.db"
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
import module_updates as mu
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

# --- 1. Migration ----------------------------------------------------------
cols = [r[1] for r in sqlite3.connect(DB).execute("PRAGMA table_info(installations)")]
check("Spalte deployer_instance_name", "deployer_instance_name" in cols, str(cols))
check("Spalte deployer_token", "deployer_token" in cols, str(cols))

# --- 2. Anlage anlegen + edit speichert Deployer-Felder (Token verschlüsselt)
r = c.post("/admin/installations", data={
    "name": "Testanlage", "url": "https://anlage.example",
    "auth_id": "", "auth_pass": "", "client_secret": "", "is_starface10": "1"})
check("Anlage angelegt", r.status_code in (200, 303), f"{r.status_code}")
inst_id = sqlite3.connect(DB).execute(
    "SELECT id FROM installations WHERE name='Testanlage'").fetchone()[0]

r = c.post(f"/admin/installations/{inst_id}", data={
    "name": "Testanlage", "url": "https://anlage.example",
    "auth_id": "", "auth_pass": "", "client_secret": "",
    "module_instance_name": "", "monitoring_instance_name": "",
    "deployer_instance_name": "UpdateDeployer", "deployer_token": "geheim123",
    "is_starface10": "1"})
stored = sqlite3.connect(DB).execute(
    "SELECT deployer_instance_name, deployer_token FROM installations WHERE id=?",
    (inst_id,)).fetchone()
check("Instanzname gespeichert", stored[0] == "UpdateDeployer", str(stored))
check("Token verschlüsselt in DB", stored[1] != "geheim123", stored[1])
check("Token-Roundtrip", app_main._decrypt(stored[1]) == "geheim123",
      str(app_main._decrypt(stored[1]) if stored[1] else ""))

# --- 3. GET /admin/updates ---------------------------------------------------
r = c.get("/admin/updates")
check("GET /admin/updates -> 200", r.status_code == 200, str(r.status_code))
html = r.text
check("Anlagenname sichtbar", "Testanlage" in html)
check("Deployer-Instanz sichtbar", "UpdateDeployer" in html)
check("mind. ein Modul-Button", "Update anstoßen" in html)

# --- 3b. Button-Beschriftung: Modul NICHT installiert -> "Installation anstoßen" --
# Mock der IST-Status-Funktion: CallBlocker fehlt, TelefonieMonitoring ok.
r = c.post(f"/admin/installations/{inst_id}", data={
    "name": "Testanlage", "url": "https://anlage.example",
    "auth_id": "", "auth_pass": "", "client_secret": "",
    "module_instance_name": "", "monitoring_instance_name": "TelefonieMonitoring",
    "deployer_instance_name": "UpdateDeployer", "deployer_token": "geheim123",
    "is_starface10": "1"})
check("Anlage mit Monitoring-Instanz aktualisiert", r.status_code in (200, 303),
      f"{r.status_code}")

import monitoring as _mon
def fake_st(inst, token, name):
    return {"list": [
        {"name": "TelefonieMonitoring", "installed": True,
         "status": "ok", "version_ist": 8},
        {"name": "CallBlocker", "installed": False,
         "status": None, "version_ist": None},
    ]}
_mon._collect_module_status = fake_st
app_main._get_token = lambda inst: "oauthtok"  # OAuth-Flow ist hier nicht Gegenstand
r = c.get("/admin/updates")
check("GET /admin/updates nach Mock -> 200", r.status_code == 200, str(r.status_code))
idx = r.text.find("<td>CallBlocker</td>")
check("Installation anstoßen bei fehlendem Modul", "Installation anstoßen" in r.text,
      repr(r.text[idx:idx + 420]) if idx >= 0 else "CallBlocker-Zeile nicht gefunden")
check("Update anstoßen bei installiertem Modul", "Update anstoßen" in r.text)

# --- 3c. Sammel-Buttons (push-all): Anzeige + Auswahl-Logik ---------------------
check("Sammel-Button 'Fehlende Module installieren' sichtbar",
      r.text.count("Fehlende Module installieren") >= 1)
check("Sammel-Button 'Module aktualisieren' sichtbar",
      r.text.count("Module aktualisieren") >= 1)
check("Sammel-Buttons zeigen auf /admin/updates/push-all",
      r.text.count("action=\"/admin/updates/push-all\"") == 2)

pushed = []
orig_push = app_main._push_module  # echte Funktion sichern (Restore am Ende von 3c)
def rec_push(inst, module_name, filename, version):
    pushed.append(module_name)
    return "ok", f"{module_name}: Update angestoßen"
app_main._push_module = rec_push

# mode=install -> nur CallBlocker (fehlt), TelefonieMonitoring NICHT
r = c.post("/admin/updates/push-all", data={
    "installation_id": str(inst_id), "mode": "install"})
check("push-all install -> Redirect wird gefolgt (200)", r.status_code == 200, str(r.status_code))
check("push-all install: nur fehlende Module angestoßen",
      pushed == ["CallBlocker"], repr(pushed))
check("push-all install: Meldung im HTML",
      "CallBlocker: Update angestoßen" in r.text, "msg-Banner fehlt")

# mode=update -> TelefonieMonitoring veraltet (v7 != SOLL v8) -> genau das eine Update
def fake_st2(inst, token, name):
    return {"list": [
        {"name": "TelefonieMonitoring", "installed": True,
         "status": "ok", "version_ist": 7},
        {"name": "CallBlocker", "installed": False,
         "status": None, "version_ist": None},
    ]}
_mon._collect_module_status = fake_st2
pushed.clear()
r = c.post("/admin/updates/push-all", data={
    "installation_id": str(inst_id), "mode": "update"})
check("push-all update: nur veraltete installierte Module angestoßen",
      pushed == ["TelefonieMonitoring"], repr(pushed))

# mode=update, ALLE aktuell -> nichts anstoßen
def fake_st3(inst, token, name):
    return {"list": [
        {"name": "TelefonieMonitoring", "installed": True,
         "status": "ok", "version_ist": 8},
        {"name": "CallBlocker", "installed": True,
         "status": "ok", "version_ist": 29},
    ]}
_mon._collect_module_status = fake_st3
pushed.clear()
r = c.post("/admin/updates/push-all", data={
    "installation_id": str(inst_id), "mode": "update"})
check("push-all update: bei aktuellen Modulen kein Push",
      pushed == [], repr(pushed))
check("push-all update: Hinweis 'bereits aktuell' im HTML",
      "Alle Module sind bereits aktuell." in r.text, "Hinweis-Banner fehlt")
app_main._push_module = orig_push  # echte Implementierung wiederherstellen (Sektion 4 testet den Einzel-Push)

# --- 4. POST /admin/updates/push (gemockt) -------------------------------------
calls = {}
def fake_push(inst, token, **kw):
    calls["token"] = token
    calls.update(kw)
    return {"status": "ok", "message": "ok", "raw": "<methodResponse>ok</methodResponse>"}

mu.push_update = fake_push
app_main._get_token = lambda inst: "oauthtok"  # OAuth-Flow ist hier nicht Gegenstand
from monitoring import _module_expectations
m = _module_expectations()
mod_name, mod_info = next(iter(m.items()))

r = c.post("/admin/updates/push", data={
    "installation_id": str(inst_id), "module_name": mod_name,
    "filename": mod_info["file"], "version": str(mod_info["version"])})
check("Push folgt Redirect", r.status_code == 200 and "/admin/updates" in r.url.path,
      f"{r.status_code} {r.url}")
check("push_update: filename", calls.get("filename") == mod_info["file"], str(calls))
check("push_update: version", calls.get("target_version") == str(mod_info["version"]),
      str(calls))
check("push_update: Token aus Anlagen-Config", calls.get("update_token") == "geheim123",
      str(calls))
check("Erfolg in UI sichtbar", "Update angestoßen" in r.text,
      repr(r.url) + " | " + r.text[:600].replace("\n", " "))
check("Statusmeldung hat OK-Button (ausblenden per onclick)",
      "this.closest('.msg')" in r.text, "OK-Button fehlt")

def fail_push(inst, token, **kw):
    return {"status": "error", "message": "Testanlage nicht erreichbar"}

mu.push_update = fail_push
r = c.post("/admin/updates/push", data={
    "installation_id": str(inst_id), "module_name": mod_name,
    "filename": mod_info["file"], "version": str(mod_info["version"])})
check("Fehler in UI sichtbar", "Testanlage nicht erreichbar" in r.text,
      r.text[-400:])

# --- 5. Ungültige installation_id --------------------------------------------
r = c.post("/admin/updates/push", data={
    "installation_id": "99999", "module_name": mod_name,
    "filename": mod_info["file"], "version": str(mod_info["version"])})
check("Unbekannte Anlage -> redirect ohne Crash",
      r.status_code in (200, 303) and "/admin/updates" in r.url.path,
      f"{r.status_code} {r.url}")

# --- 6. Modul-Seite (/admin/modules): Icon-Download + Dokumentation (PDF) -----
conn2 = sqlite3.connect(DB)
conn2.execute(
    "INSERT OR REPLACE INTO modules (name, filename, version, app_version, description, "
    "file_size, file_hash, file_mtime) VALUES (?,?,?,?,?,?,?,?)",
    ("CallBlocker", "CallBlocker.sfm", 29, "v0.0.188", "Test-Beschreibung",
     12024, "a" * 64, "2026-08-26 20:24:48"))
conn2.commit()
conn2.close()
r = c.get("/admin/modules")
check("Modul-Seite: Spalte 'Dokumentation' vorhanden",
      ">Dokumentation<" in r.text, "")
check("Modul-Seite: PDF-Link je Modul (/static/docs/…)",
      "/static/docs/CallBlocker.pdf" in r.text, "")
check("Modul-Seite: Download-Button ohne Text 'Download'",
      ">Download<" not in r.text, "alter Text-Link noch da")
check("Modul-Seite: Download-Icon (Title '.sfm-Datei herunterladen')",
      'title=".sfm-Datei herunterladen"' in r.text, "")
check("Modul-Seite: Statusmeldung 'Verfügbare Module'",
      "Verfügbare Module" in r.text, "")

print("\n" + ("ERGEBNIS: ALLE ADMIN-UPDATES-TESTS OK"
              if not FAIL else f"FEHLGESCHLAGEN: {FAIL}"))
sys.exit(0 if not FAIL else 1)
