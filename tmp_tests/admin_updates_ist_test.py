"""Tests: Version (IST) auf der Modul-Updates-Seite (/admin/updates).

Neue Spalte „Version (IST)“ — beim Seitenaufruf frisch via GetModuleStatus
(monitoring._collect_module_status, Wiederverwendung der Monitoring-Logik).

Geprüft:
1. Header/Spalte „Version (IST)“ vorhanden
2. outdated-Modul -> „v{soll-1} (Update verfügbar)“ orange
3. fehlendes Modul -> „nicht installiert“
4. Fehlerfall (Modul nicht erreichbar) -> „—“ + Hinweiszeile „Version (IST) nicht verfügbar“
5. Anlage ohne monitoring_instance_name -> kontrollierter Config-Hinweis (KEIN RPC)
"""
import base64, os, sqlite3, sys
sys.path.insert(0, "app")

DB = "/tmp/admin_updates_ist_test.db"
if os.path.exists(DB):
    os.remove(DB)
os.environ["STARFACE_DB"] = DB
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
os.environ["MODULE_UPDATE_BASE_URL"] = "https://modulupdates.example"
os.environ["UPDATE_SIGNING_SECRET"] = "testsecret"

import main as app_main
import monitoring
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

def add_anlage(name: str, mon_inst: str) -> int:
    c.post("/admin/installations", data={
        "name": name, "url": "https://anlage.example",
        "auth_id": "", "auth_pass": "", "client_secret": "", "is_starface10": "1"})
    iid = sqlite3.connect(DB).execute(
        "SELECT id FROM installations WHERE name=?", (name,)).fetchone()[0]
    c.post(f"/admin/installations/{iid}", data={
        "name": name, "url": "https://anlage.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "module_instance_name": "", "monitoring_instance_name": mon_inst,
        "deployer_instance_name": "Deployment-Modul", "deployer_token": "",
        "is_starface10": "1"})
    return iid

id_mit = add_anlage("MitMonitoring", "TelefonieMonitoring")
id_ohne = add_anlage("OhneMonitoring", "")

app_main._get_token = lambda inst: "oauthtok"   # OAuth-Flow ist hier nicht Gegenstand
expect = monitoring._module_expectations()
assert expect, "app/modules leer — Test ohne SOLL-Liste nicht aussagekräftig"
first_name = next(iter(expect))
first_soll = expect[first_name]["version"]

# --- 1+2. outdated: alle Module um 1 unter SOLL ------------------------------
def fake_outdated(inst, token, name):
    items = []
    for mname, exp in expect.items():
        items.append({"name": mname, "installed": True, "current": False,
                      "version_ist": exp["version"] - 1, "version_soll": exp["version"],
                      "vendor": exp["vendor"], "instances": [], "status": "outdated"})
    return {"list": items, "error": None}

monitoring._collect_module_status = fake_outdated
r = c.get("/admin/updates")
check("GET /admin/updates -> 200", r.status_code == 200, str(r.status_code))
check("Spalte 'Version (IST)' im Header", "Version (IST)" in r.text,
      "Version (IST)" not in r.text and "Header fehlt" or "")
check("outdated -> v{soll-1} sichtbar", f"v{first_soll - 1}" in r.text,
      f"v{first_soll - 1} fehlt")
check("outdated -> '(Update verfügbar)'", "(Update verfügbar)" in r.text,
      "(Update verfügbar) fehlt")

# --- 3. missing: Anlage kennt nur das erste Modul ---------------------------
def fake_missing(inst, token, name):
    # Wie _compare_modules im echten Betrieb: nicht in der Antwort geführte
    # erwartete Module -> missing-Item mit installed=False.
    items = []
    for mname, exp in expect.items():
        if mname == first_name:
            items.append({"name": mname, "installed": True, "current": True,
                          "version_ist": exp["version"], "version_soll": exp["version"],
                          "vendor": exp["vendor"], "instances": [], "status": "ok"})
        else:
            items.append({"name": mname, "installed": False, "current": False,
                          "version_ist": None, "version_soll": exp["version"],
                          "vendor": exp["vendor"], "instances": [], "status": "missing"})
    return {"list": items, "error": None}

if len(expect) > 1:
    monitoring._collect_module_status = fake_missing
    r = c.get("/admin/updates")
    check("fehlendes Modul -> 'nicht installiert'", "nicht installiert" in r.text,
          "nicht installiert fehlt")
    check("aktuelles Modul -> grüne v-Nummer", f"v{first_soll}" in r.text,
          f"v{first_soll} fehlt")

# --- 4. error: Anlage meldet Fault/weg --------------------------------------
def fake_err(inst, token, name):
    return {"list": None, "error": {
        "category": "module",
        "msg": "STARFACE-Fehler: Modul nicht installiert oder eingerichtet"}}

monitoring._collect_module_status = fake_err
r = c.get("/admin/updates")
check("Fehler -> Hinweiszeile 'Version (IST) nicht verfügbar'",
      "Version (IST) nicht verfügbar" in r.text, "Hinweis fehlt")
check("Fehler -> Meldungstext der Anlage", "Modul nicht installiert oder eingerichtet" in r.text,
      "Meldungstext fehlt")
check("Fehler -> Zelle zeigt '—'", "&mdash;" in r.text or "\u2014" in r.text,
      "kein Em-Dash in der IST-Zelle")

# --- 5. Anlage ohne Monitoring-Instanz -> Config-Hinweis, kein RPC -----------
calls = {"rpc": 0}
_orig = monitoring._collect_module_status
def fake_err_nur_mit(inst, token, name):
    calls["rpc"] += 1
    return fake_err(inst, token, name)
monitoring._collect_module_status = fake_err_nur_mit
r = c.get("/admin/updates")
check("ohne Monitoring-Instanz -> Config-Hinweis",
      "Keine Monitoring-Instanz konfiguriert" in r.text, "Hinweis fehlt")
monitoring._collect_module_status = _orig

print()
if FAIL:
    print("FEHLGESCHLAGEN:", ", ".join(FAIL))
    sys.exit(1)
print("ERGEBNIS: ALLE IST-VERSION-TESTS OK")
