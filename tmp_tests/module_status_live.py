#!/usr/bin/env python3
"""Live-Beweis Modul-Status: echte DB + echter collect_installations-Poll (XML-RPC
gemockt) → /monitoring-Seite + /api/monitoring/status über TestClient (Volllogin).

Szenarien:
  PBX-GUT    → GetStats ok + GetModuleStatus ok   → API modules ok (Karte geparkt)
  PBX-TEIL   → GetStats ok + GetModuleStatus ok   → API outdated+missing
  PBX-FAULT  → GetStats Fault                     → API modules.error Kategorie module

Seit v1.0.58 (F65): Die Modul-Status-Karte ist von /monitoring GEPARKT (kommt später
woanders hin) — die Seite darf sie nicht mehr zeigen, die API muss die Daten aber
weiterhin liefern (Datenfluss unverändert).
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
    "Überschrift Monitoring-Übersicht": "Monitoring-Übersicht" in h,
    "Modul-Status-Karte GEPARKT (nicht mehr auf /monitoring)": "card-modules" not in h
        and "Modul-Status" not in h and "mod-rows" not in h,
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
# Diagnose-Route /api/monitoring/module-status-raw wurde in v0.0.148 entfernt
# (Rohdaten-Block in der UI entfernt, Endpoint weg — der _collect_module_status-Pfad
# oben deckt die GetModuleStatus-Verarbeitung ab).
print("\nLIVE-BEWEIS MODUL-STATUS OK")
