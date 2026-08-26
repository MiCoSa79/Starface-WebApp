#!/usr/bin/env python3
"""Live-Beweis Modul-Status: echte DB + echter collect_installations-Poll (XML-RPC
gemockt) → /monitoring-Seite + /api/monitoring/status über TestClient (Volllogin).

Szenarien:
  PBX-GUT    → GetStats ok + GetModuleStatus ok   → Karte: CallBlocker Aktuell
  PBX-TEIL   → GetStats ok + GetModuleStatus ok   → CallBlocker outdated, TM missing
  PBX-FAULT  → GetStats Fault                     → Hinweis „Monitoring-Modul
             nicht installiert oder eingerichtet“
"""
import os, sys, sqlite3, tempfile, json, time

DB = tempfile.mktemp(suffix=".db")
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ.setdefault("APP_VERSION", "v9.9.9-LIVE")
for var in ("FERNET_KEY", "TOTP_ISSUER"):
    os.environ.pop(var, None)
MODDIR = os.path.join(os.path.dirname(__file__), "module_status_fakes")
os.environ["MODULES_DIR"] = MODDIR  # CallBlocker v28 + TelefonieMonitoring v5 (Fakes)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import main as app_main
import monitoring
from starlette.testclient import TestClient

app_main.init_db()
import bcrypt
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,1)",
             ("admin", bcrypt.hashpw(b"test1234", bcrypt.gensalt()).decode()))
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES (?,?,?,1)",
             ("PBX-GUT", "http://gut.invalid", "TelefonieMonitoring"))
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES (?,?,?,1)",
             ("PBX-TEIL", "http://teil.invalid", "TelefonieMonitoring"))
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES (?,?,?,1)",
             ("PBX-FAULT", "http://fault.invalid", "TelefonieMonitoring"))
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name, is_starface10) VALUES (?,?,?,1)",
             ("PBX-ALT", "http://alt.invalid", "TelefonieMonitoring"))
conn.commit(); conn.close()

INSTALLED_OK = json.dumps([
    {"name": "CallBlocker", "version": 28, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
    {"name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
])
INSTALLED_ALT = json.dumps([
    {"name": "CallBlocker", "version": 27, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
])

def fake_xmlrpc(url, token, method, params=None, instance_name=None):
    if "fault" in url:
        raise RuntimeError("STARFACE-Fehler: unknown method -> Monitoring-Modul fehlt")
    if "alt" in url and method == "GetModuleStatus":
        # Anlage hat Monitoring-Modul v4: GetStats lief, GetModuleStatus existiert nicht
        raise RuntimeError("STARFACE-Fehler: unknown method GetModuleStatus")
    if method == "GetStats":
        return {"members": {"systemName": "pbx-demo", "systemVersion": "10.0.2.5",
                            "providerStatus": "sip01@pbx-demo=Registered"}}
    if method == "GetModuleStatus":
        return {"members": {"moduleJson": INSTALLED_OK if "gut" in url else INSTALLED_ALT}}
    raise AssertionError(f"unbekannte Methode {method}")

monitoring._get_token = lambda inst: "tok"
monitoring._xmlrpc = fake_xmlrpc

ok = monitoring.collect_installations()
print(f"Poll: writes={ok}, Anlagen mit Modul-Daten: "
      f"{sum(1 for v in monitoring._state['last_values'].values() if v.get('modules', {}).get('list'))}/3")

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "test1234"})
assert r.status_code == 200 and r.json().get("status") == "ok", (r.status_code, r.text[:200])
r = c.get("/monitoring")
assert r.status_code == 200, f"/monitoring {r.status_code}"
h = r.text

checks = {
    "Karte vorhanden": "Modul-Status (eigene Module)" in h,
    "CallBlocker Aktuell (PBX-GUT)": 'title="Installierte Version entspricht der ausgelieferten."' in h,
    "CallBlocker outdated (PBX-TEIL)": 'title="Auf der Anlage ist eine ältere Version installiert."' in h,
    "TelefonieMonitoring missing (PBX-TEIL)": "Nicht installiert" in h,
    "PBX-FAULT-Hinweis in Karte": "Monitoring-Modul nicht installiert oder eingerichtet" in h,
    "PBX-ALT zu alt -> Update auf v5 (NICHT v28!)": ("Update auf v5 erforderlich" in h
                                                     and "v28 erforderlich" not in h),
    "Version 27 → 28": "v27 → v28" in h,
    "keine Emojis": "✓" not in h and "⚠" not in h,
    "Instanz aktiv": "CallBlocker (aktiv)" in h,
}
failed = [k for k, v in checks.items() if not v]
for k, v in checks.items():
    print(("OK  " if v else "FAIL") + f" /monitoring: {k}")
assert not failed, failed

r = c.get("/api/monitoring/status")
st = r.json()
insts = st["installations"]
assert insts["PBX-GUT"]["modules"]["list"][0]["status"] == "ok"
assert insts["PBX-TEIL"]["modules"]["list"][0]["status"] == "outdated"
assert insts["PBX-TEIL"]["modules"]["list"][1]["status"] == "missing"
assert insts["PBX-FAULT"]["modules"]["list"] is None
assert insts["PBX-FAULT"]["modules"]["error"]["category"] == "module"
assert insts["PBX-ALT"]["modules"]["list"] is None
assert insts["PBX-ALT"]["modules"]["error"]["msg"] == \
    "Monitoring-Modul-Version zu alt — GetModuleStatus fehlt (Update auf v5 erforderlich)", \
    insts["PBX-ALT"]["modules"]["error"]
assert st["last_error"]["category"] == "module"
print("OK   /api/monitoring/status: PBX-GUT ok / PBX-TEIL outdated+missing / PBX-FAULT module-Fehler / PBX-ALT zu-alt-nennt-v5 (Kategorie)")

# --- Diagnose-Route: ungefilterte GetModuleStatus-Antwort (Admin) ---
# Regression v0.0.144: Route holte nur name/url/monitoring_instance_name -> echter
# _get_token(row) scheiterte mit KeyError (fehlende Auth-Spalten) -> "Kein Token".
# Der bisherige Lambda-Mock hat das maskiert. Fake prüft jetzt die Spalten!
def fake_get_token_row_check(inst):
    # Achtung: bei sqlite3.Row prüft "k in inst" die WERTE (Sequenz), nicht die
    # Keys — deshalb inst.keys() verwenden!
    have = set(inst.keys())
    missing = [k for k in ("auth_id", "auth_pass", "client_secret",
                           "is_starface10", "oauth_access", "oauth_refresh",
                           "oauth_expires") if k not in have]
    if missing:
        raise KeyError(f"fehlende Spalten in installations-Zeile: {missing}")
    return "tok"
app_main._get_token = fake_get_token_row_check
app_main._xmlrpc = fake_xmlrpc
r = c.get("/api/monitoring/module-status-raw?installation=PBX-GUT")
j = r.json()
assert r.status_code == 200 and j["ok"] and j["fault"] is None \
    and j["raw"] == INSTALLED_OK and j["expected"] == ["CallBlocker", "TelefonieMonitoring"], \
    (r.status_code, j)
assert "stats_diag" in j, j  # v7-Diagnosefeld vorhanden (Fake liefert kein moduleDiag -> None)
r = c.get("/api/monitoring/module-status-raw?installation=PBX-ALT")
j = r.json()
assert j["ok"] and j["raw"] is None and "GetModuleStatus" in (j["fault"] or ""), j
r = c.get("/api/monitoring/module-status-raw?installation=GIBTSNICHT")
assert r.status_code == 404, r.status_code
c2 = TestClient(app_main.app)  # ohne Login -> 401
r = c2.get("/api/monitoring/module-status-raw?installation=PBX-GUT")
assert r.status_code == 401, r.status_code
print("OK   Diagnose-Route: raw=INSTALLED_OK (PBX-GUT) / fault GetModuleStatus (PBX-ALT) / 404 unbekannt / 401 ohne Login")
print("\nLIVE-BEWEIS MODUL-STATUS OK")
