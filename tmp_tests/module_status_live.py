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
    if method == "GetStats":
        return {"members": {"systemName": "pbx-demo", "systemVersion": "10.0.2.5",
                            "providerStatus": "sip01@pbx-demo=Registered"}}
    if method == "GetModuleStatus":
        return {"moduleJson": INSTALLED_OK if "gut" in url else INSTALLED_ALT}
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
assert st["last_error"]["category"] == "module"
print("OK   /api/monitoring/status: PBX-GUT ok / PBX-TEIL outdated+missing / PBX-FAULT module-Fehler (Kategorie)")
print("\nLIVE-BEWEIS MODUL-STATUS OK")
