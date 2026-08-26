"""T4b-Tests: Admin-UI 'Download-Test (Ping)' — P1-Fernbeweis ohne Credential-Export.

Geprüft:
1. Ping-Button auf /admin/updates vorhanden
2. Anlage ohne deployer_instance_name -> "Keine Deployer-Instanz" (echte Funktion, kein Netz)
3. Unbekannte Anlage -> "Unbekannte Anlage."
4. Erfolg (ping_channel gemockt): Statuszeile + korrekte Args (filename, token, instance_name)
5. Fehler (ping_channel gemockt): FEHLER-Meldung in der UI
"""
import base64, os, sqlite3, sys
sys.path.insert(0, "app")

DB = "/tmp/admin_updates_ping_test.db"
if os.path.exists(DB):
    os.remove(DB)
os.environ["STARFACE_DB"] = DB
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
os.environ["MODULE_UPDATE_BASE_URL"] = "https://modulupdates.example"
os.environ["UPDATE_SIGNING_SECRET"] = "testsecret"

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

def add_anlage(name, with_deployer: bool) -> int:
    c.post("/admin/installations", data={
        "name": name, "url": "https://anlage.example",
        "auth_id": "", "auth_pass": "", "client_secret": "", "is_starface10": "1"})
    iid = sqlite3.connect(DB).execute(
        "SELECT id FROM installations WHERE name=?", (name,)).fetchone()[0]
    c.post(f"/admin/installations/{iid}", data={
        "name": name, "url": "https://anlage.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "module_instance_name": "", "monitoring_instance_name": "",
        "deployer_instance_name": "UpdateDeployer" if with_deployer else "",
        "deployer_token": "", "is_starface10": "1"})
    return iid

# --- 1. Anlagen (eine OHNE deployer_instance_name, eine MIT) ----------------
id_ohne = add_anlage("OhneDeployer", with_deployer=False)
id_mit = add_anlage("MitDeployer", with_deployer=True)

# --- 1b. Ping-Button auf der Seite (Tabelle erscheint pro Anlage) -----------
r = c.get("/admin/updates")
check("GET /admin/updates -> 200", r.status_code == 200, str(r.status_code))
check("Ping-Button vorhanden", r.text.count("Download-Test") >= 1,
      "Download-Test" not in r.text and "fehlt" or "")

# --- 3. Anlage ohne Deployer-Instanz -> kontrollierter Fehler (KEIN Netz) ---
app_main._get_token = lambda inst: "oauthtok"  # OAuth-Flow ist hier nicht Gegenstand
r = c.post("/admin/updates/ping", data={
    "installation_id": str(id_ohne), "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm"}, follow_redirects=False)
check("ohne Instanz -> Redirect 303", r.status_code == 303,
      f"s={r.status_code} loc={r.headers.get('location')}")
check("ohne Instanz -> Redirect auf /admin/updates",
      (r.headers.get("location") or "").startswith("/admin/updates"),
      r.headers.get("location", ""))
r = c.post("/admin/updates/ping", data={
    "installation_id": str(id_ohne), "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm"}, follow_redirects=True)
check("ohne Instanz -> 'Keine Deployer-Instanz'",
      "Keine Deployer-Instanz" in r.text,
      "Keine Deployer-Instanz" not in r.text and r.text[-250:] or "")

# --- 4. Unbekannte Anlage ---------------------------------------------------
r = c.post("/admin/updates/ping", data={
    "installation_id": "9999", "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm"}, follow_redirects=True)
check("unbekannte Anlage -> 'Unbekannte Anlage.'", "Unbekannte Anlage" in r.text,
      "Unbekannte Anlage" not in r.text and r.text[-150:] or "")

# --- 4b. PUSH (echte push_update, OHNE Mock) an Anlage ohne Instanz ---------
# Regressionsschutz: push_update darf auf echten sqlite3-Rows nicht crashen.
r = c.post("/admin/updates/push", data={
    "installation_id": str(id_ohne), "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm", "version": "1"},
    follow_redirects=True)
check("Push (echt, ohne Instanz) -> 'Keine Deployer-Instanz'",
      "Keine Deployer-Instanz" in r.text,
      "Keine Deployer-Instanz" not in r.text and r.text[-200:] or "")

# --- 5. Erfolg: ping_channel gemockt, Argumente geprüft ----------------------
fake_calls = {}
def fake_ping(inst, token, *, filename, instance_name=None):
    fake_calls["filename"] = filename
    fake_calls["token"] = token
    fake_calls["inst"] = instance_name or inst.get("deployer_instance_name")
    return {"status": "ok", "message": "ok",
            "raw": "<methodResponse><params><param><value><string>HTTP 200 (4210 bytes)</string></value></param></params></methodResponse>",
            "response": "HTTP 200 (4210 bytes)"}
mu.ping_channel = fake_ping

r = c.post("/admin/updates/ping", data={
    "installation_id": str(id_mit), "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm"}, follow_redirects=True)
check("Erfolg -> Statuszeile 'Download-Test ok'", "Download-Test ok" in r.text,
      "Download-Test ok" not in r.text and r.text[:400] or "")
check("Erfolg -> Antwort sichtbar", "HTTP 200 (4210 bytes)" in r.text,
      "HTTP 200" not in r.text and r.text[:400] or "")
check("Ping-Args: filename", fake_calls.get("filename") == "UpdateDeployer.sfm", str(fake_calls))
check("Ping-Args: token aus WebApp", fake_calls.get("token") == "oauthtok", str(fake_calls))
check("Ping-Args: Instanzname", fake_calls.get("inst") == "UpdateDeployer", str(fake_calls))

# --- 6. Fehlerfall: ping_channel liefert error ------------------------------
mu.ping_channel = lambda inst, token, **kw: {
    "status": "error", "message": "Testanlage nicht erreichbar"}
r = c.post("/admin/updates/ping", data={
    "installation_id": str(id_mit), "module_name": "UpdateDeployer",
    "filename": "UpdateDeployer.sfm"}, follow_redirects=True)
check("Fehler -> FEHLER-Meldung in UI", "FEHLER" in r.text and "nicht erreichbar" in r.text,
      "nicht erreichbar" not in r.text and r.text[:400] or "")

# --- 7. Fallback-Import (Container: 'monitoring' nicht top-level) -----------
import sys as _sys
_orig_mod = _sys.modules.get("monitoring")
_sys.modules["monitoring"] = None           # erzwingt ImportError auf Weg 1
_sys.path.insert(0, os.getcwd())            # repo-root, damit 'from app import ...' greift
r = c.get("/admin/updates")
_sys.path.pop(0)
if _orig_mod is not None:
    _sys.modules["monitoring"] = _orig_mod
else:
    del _sys.modules["monitoring"]
check("Fallback-Import (app.monitoring) -> Seite 200",
      r.status_code == 200 and "Download-Test" in r.text,
      f"status={r.status_code}")

print()
if FAIL:
    print("FEHLGESCHLAGEN:", ", ".join(FAIL))
    sys.exit(1)
print("ERGEBNIS: ALLE ADMIN-UPDATES-PING-TESTS OK")
