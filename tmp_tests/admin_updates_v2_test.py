"""F73-Tests: Modul-Updates (Variante 1 „nach Anlage“ + Variante 2 „nach Modul“).

Geprüft:
1. Submenü: „Updates nach Anlage“ + „Updates nach Modul“ im Admin-Dropdown
2. V1-Leerzustand: /admin/updates ohne inst_id -> Combobox (Suchfunktion) + Hinweis, KEINE Tabelle
3. V1-Auswahl: ?inst_id=<mit> -> Modul-Tabelle NUR der gewählten Anlage
4. V2-Leerzustand: /admin/updates/modul -> Combobox + „Bitte oben ein Modul auswählen“
5. V2-Filter: nur „installiert + nicht aktuell“; Checkboxen; Alle auswählen/Auswahl aufheben;
   Bulk-Formular -> /admin/updates/push-module; Zeilen-Button nur mit Deployment-Modul
6. POST push-module (Bulk): _push_module je Anlage; Redirect behält Modul-Auswahl + Meldung
7. Kontext-Redirects: /admin/updates/push behält inst_id in der Location

Aufruf: python3 tmp_tests/admin_updates_v2_test.py
"""
import base64
import os
import sqlite3
import sys
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_updates_v2_test/test.db"
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
import monitoring
from starlette.testclient import TestClient

app_main.init_db()
import bcrypt
conn = sqlite3.connect(DB)
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


# --- Fixture: zwei Anlagen (mit/ohne Deployment-Modul-Instanz, beide mit Monitoring)
def add_anlage(name, dep_inst):
    r = c.post("/admin/installations", data={
        "name": name, "url": f"https://{name.lower()}.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "is_starface10": "1"})
    assert r.status_code in (200, 303), f"Anlage {name}: {r.status_code}"
    iid = sqlite3.connect(DB).execute(
        "SELECT id FROM installations WHERE name=?", (name,)).fetchone()[0]
    # Instanz-Namen (Monitoring/Deployment-Modul) sind bewusst nur über
    # „Anlage bearbeiten“ setzbar (Neuanlage-Formular führt sie nicht)
    r = c.post(f"/admin/installations/{iid}", data={
        "name": name, "url": f"https://{name.lower()}.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "module_instance_name": "", "monitoring_instance_name": "TelefonieMonitoring",
        "deployer_instance_name": dep_inst, "deployer_token": "",
        "is_starface10": "1"})
    assert r.status_code in (200, 303), f"Edit {name}: {r.status_code}"
    return iid


id_mit = add_anlage("MitDeployer", "Deployment-Modul")
id_ohne = add_anlage("OhneDeployer", "")

expect = monitoring._module_expectations()
assert expect, "app/modules leer — Test ohne SOLL-Liste nicht aussagekräftig"
names = list(expect)
mod_a, mod_b = names[0], names[1] if len(names) > 1 else names[0]
soll_a = expect[mod_a]["version"]

# --- 1. Submenü in der Navigation (auf jeder Administration-Seite) ---------------
r = c.get("/admin/updates")
check("Submenü: 'Updates nach Anlage' im Menü", "Updates nach Anlage" in r.text)
check("Submenü: 'Updates nach Modul' im Menü", "Updates nach Modul" in r.text)
check("Submenü-Linkziel Variante 2", 'href="/admin/updates/modul"' in r.text)

# --- 2. Variante 1: Leerzustand --------------------------------------------------
r = c.get("/admin/updates")
check("V1 leer: 200", r.status_code == 200, str(r.status_code))
check("V1 leer: Combobox mit Suchfunktion vorhanden",
      'data-cb="update-anlage"' in r.text and "cb-search" in r.text)
check("V1 leer: Hinweis 'Bitte oben eine Anlage auswählen'",
      "Bitte oben eine Anlage auswählen" in r.text)
check("V1 leer: KEINE Modul-Tabelle (noch keine Auswahl)",
      "Version (SOLL)" not in r.text)
check("V1 leer: KEIN Aktions-Button", "Update anstoßen" not in r.text)
check("V1: admin.js eingebunden (initComboboxes - Regressionsschutz F74)",
      'src="/static/admin.js?v=' in r.text)

# --- 3. Variante 1: Auswahl zeigt NUR die gewählte Anlage -------------------------
r = c.get(f"/admin/updates?inst_id={id_mit}")
check("V1 Auswahl: 200", r.status_code == 200, str(r.status_code))
check("V1 Auswahl: Modul-Tabelle gerendert",
      "Version (SOLL)" in r.text and f"v{soll_a}" in r.text)
check("V1 Auswahl: gewählte Anlage als Überschrift",
      f'<h2 class="tbl-head">{ "MitDeployer" }' in r.text)
check("V1 Auswahl: andere Anlage fehlt als Überschrift",
      '<h2 class="tbl-head">OhneDeployer' not in r.text)

# --- 4. Variante 2: Leerzustand ---------------------------------------------------
r = c.get("/admin/updates/modul")
check("V2 leer: 200", r.status_code == 200, str(r.status_code))
check("V2 leer: Combobox Modul vorhanden",
      'data-cb="update-modul"' in r.text and "cb-search" in r.text)
check("V2 leer: Hinweis 'Bitte oben ein Modul auswählen'",
      "Bitte oben ein Modul auswählen" in r.text)
check("V2 leer: KEINE Tabelle", "Aktuellste Version" not in r.text)
check("V2: admin.js eingebunden (initComboboxes - Regressionsschutz F74)",
      'src="/static/admin.js?v=' in r.text)

r = c.get("/admin/updates/modul?module=GibtEsNicht")
check("V2: unbekanntes Modul -> Hinweis", "Unbekanntes Modul" in r.text)

# --- 5. Variante 2: Filter „installiert + nicht aktuell“ ---------------------------
# MitDeployer: mod_a veraltet, übrige aktuell. OhneDeployer: kein Modul installiert.
def fake_st(inst, token, name):
    items = []
    if inst["name"] == "MitDeployer":
        for mname, exp in expect.items():
            status = "outdated" if mname == mod_a else "ok"
            items.append({"name": mname, "installed": True, "current": status == "ok",
                          "version_ist": exp["version"] - (1 if status == "outdated" else 0),
                          "version_soll": exp["version"], "vendor": exp["vendor"],
                          "instances": [], "status": status})
    return {"list": items, "error": None}

monitoring._collect_module_status = fake_st
app_main._get_token = lambda inst: "oauthtok"

r = c.get(f"/admin/updates/modul?module={mod_a}")
check("V2 Filter: 200", r.status_code == 200, str(r.status_code))
check("V2 Filter: nur Anlage mit veraltetem Modul gelistet",
      "MitDeployer" in r.text and "OhneDeployer" not in r.text,
      "Zeilen falsch")
check("V2 Filter: IST-Zeile (soll-1)", f"v{expect[mod_a]['version'] - 1}" in r.text)
check("V2 Filter: aktuellste Version (SOLL)", f"v{expect[mod_a]['version']}" in r.text)
check("V2 Filter: Checkbox (Auswahl) je Zeile", 'name="installation_ids"' in r.text)
check("V2: Button 'Alle auswählen'", "Alle auswählen" in r.text)
check("V2: Button 'Auswahl aufheben'", "Auswahl aufheben" in r.text)
check("V2: Bulk-Formular -> /admin/updates/push-module",
      'action="/admin/updates/push-module"' in r.text)
check("V2: Zeilen-Button 'Update anstoßen'", "Update anstoßen" in r.text)

r = c.get(f"/admin/updates/modul?module={mod_b}")
check("V2 Filter: aktuelles Modul -> 'Keine Anlage' + keine Tabelle",
      "Keine Anlage" in r.text and "MitDeployer" not in r.text)

# OhneDeployer ist auch veraltet -> erscheint, aber ohne Aktions-Button
def fake_st2(inst, token, name):
    items = []
    for mname, exp in expect.items():
        status = "outdated" if mname == mod_a else "ok"
        items.append({"name": mname, "installed": True, "current": status == "ok",
                      "version_ist": exp["version"] - (1 if status == "outdated" else 0),
                      "version_soll": exp["version"], "vendor": exp["vendor"],
                      "instances": [], "status": status})
    return {"list": items, "error": None}

monitoring._collect_module_status = fake_st2
r = c.get(f"/admin/updates/modul?module={mod_a}")
check("V2: Anlage ohne Deployment-Modul -> 'kein Deployment-Modul' in Zeile",
      "kein Deployment-Modul" in r.text and "OhneDeployer" in r.text)
check("V2: Zeilen-Button 'Update anstoßen' nur mit Deployment-Modul (1×)",
      r.text.count("Update anstoßen") == 1, f"{r.text.count('Update anstoßen')}")

# --- 6. Bulk-Push (POST /admin/updates/push-module) --------------------------------
pushes = []


def fake_push(inst, module_name, filename, version, is_install=False):
    pushes.append((inst["name"], module_name, filename, version, is_install))
    return ("ok", f"{inst['name']}: Update angestoßen")


orig_push = app_main._push_module
app_main._push_module = fake_push

r = c.post("/admin/updates/push-module",
           data={"module_name": mod_a, "filename": expect[mod_a]["file"],
                 "version": str(expect[mod_a]["version"]),
                 "installation_ids": [str(id_mit), str(id_ohne)]},
           follow_redirects=False)
loc = r.headers.get("location", "")
check("Bulk: Redirect 303 auf Variante 2",
      r.status_code == 303 and loc.startswith("/admin/updates/modul"), loc)
check("Bulk: Modul-Auswahl bleibt erhalten", f"module={mod_a}" in loc, loc)
check("Bulk: Meldung '2× Update'", "2× Update" in unquote(loc), loc)
check("Bulk: _push_module je Anlage (2 Aufrufe)", len(pushes) == 2, str(pushes))
check("Bulk: Argumente korrekt (Modul/Datei/Version, KEIN is_install)",
      all(p[1] == mod_a and p[2] == expect[mod_a]["file"]
          and str(p[3]) == str(expect[mod_a]["version"]) and p[4] is False for p in pushes))

r = c.post("/admin/updates/push-module",
           data={"module_name": mod_a, "installation_ids": []}, follow_redirects=False)
check("Bulk: ohne Auswahl -> 'Keine Anlage ausgewählt.'",
      "Keine Anlage ausgewählt" in unquote(r.headers.get("location", "")),
      r.headers.get("location", ""))

app_main._push_module = orig_push

# --- 7. Kontext-Redirects: push behält inst_id in der Location ----------------------
r = c.post("/admin/updates/push", data={
    "installation_id": str(id_mit), "module_name": mod_a,
    "filename": expect[mod_a]["file"], "version": str(expect[mod_a]["version"])},
    follow_redirects=False)
loc = r.headers.get("location", "")
check("Push-Redirect behält inst_id (Auswahl bleibt erhalten)",
      f"inst_id={id_mit}" in loc, loc)

print()
if FAIL:
    print("FEHLGESCHLAGEN:", ", ".join(FAIL))
    sys.exit(1)
print("ERGEBNIS: ALLE MODUL-UPDATES-V2-TESTS OK")
