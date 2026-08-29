"""Tests: Drittanbietermodule auf der Modul-Seite (F44).

Geprüft:
1. Migration: modules hat Spalten source + vendor
2. POST /admin/modules/third-party (Upload): gültige .sfm → DB source='third_party',
   Datei in <data>/modules, versions.json enthält das Modul, Event geloggt
3. _module_expectations() enthält hinterlegte Drittanbieter (SOLL, source)
4. Fehlerfälle: ungültige Datei → err=invalid; falsche Endung → err=not_sfm;
   Kollision mit eigenem Modul (CallBlocker) → err=exists
5. Erneuter Upload gleicher Name andere Version → Aktualisierung (msg=updated),
   alte Datei entfernt, versions.json nur neue Version
6. Monitoring-Filter: Drittanbieter erscheinen auf der Karte nur, wenn installiert
   (filter_third_party_missing) — eigene Module immer
7. Update-Seite zeigt Drittanbieter mit Badge; Modul-Seite zwei Tabellen + Upload-Formular
8. Download der Drittanbieter-Datei (aus <data>/modules)
9. DELETE entfernt Datei + DB-Zeile + versions.json-Eintrag (Event geloggt)

Aufruf: python3 tmp_tests/third_party_modules_test.py
"""
import base64
import io
import json
import os
import sqlite3
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/third_party_modules_test/test.db"
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

app_main.init_db()  # scannt echte eigene Module (CallBlocker v30, ...)

DATA_MOD = os.path.join(os.path.dirname(app_main.DB_PATH), "modules")
VJSON = os.path.join(os.path.dirname(app_main.DB_PATH), "versions.json")


def make_sfm(path: str, name: str, version: str, vendor: str = "Fremd GmbH",
             description: str = "Testmodul") -> str:
    desc = (f'<module name="{name}" version="{version}" specVersion="5" '
            f'vendor="{vendor}"><description>{description}</description></module>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("module-descriptor.xml", desc)
    return path


def upload(client, sfm_path: str, orig_name: str = "modul.sfm"):
    with open(sfm_path, "rb") as fh:
        return client.post("/admin/modules/third-party",
                           files={"module_file": (orig_name, fh,
                                                  "application/octet-stream")})


def manifest_modules():
    with open(VJSON, encoding="utf-8") as fh:
        return {m["moduleName"]: m["versions"] for m in json.load(fh)["modules"]}


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


def loc(r) -> str:
    """Location des (letzten) 3xx-Redirects — TestClient folgt Redirects,
    der ursprüngliche Location-Header steckt dann in r.history."""
    for h in reversed(r.history or []):
        if h.status_code in (301, 302, 303):
            return h.headers.get("location", "")
    return r.headers.get("location", "")


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# --- 1. Migration -----------------------------------------------------------
cols = [r[1] for r in sqlite3.connect(DB).execute("PRAGMA table_info(modules)")]
check("Spalte source", "source" in cols, str(cols))
check("Spalte vendor", "vendor" in cols, str(cols))
own_sources = set(sqlite3.connect(DB).execute(
    "SELECT source FROM modules WHERE name = 'CallBlocker'").fetchall()[0])
check("Eigene Module source='own'", own_sources == {"own"}, str(own_sources))
cb_before = sqlite3.connect(DB).execute(
    "SELECT version, source FROM modules WHERE name = 'CallBlocker'").fetchone()

# --- 2. Upload gültiges Drittanbietermodul ----------------------------------
sfm1 = "/tmp/third_party_modules_test/drittanbieter_v7.sfm"
make_sfm(sfm1, "Drittanbieter Test", "7", vendor="Fremd GmbH",
         description="Ein fremdes Testmodul")
r = upload(c, sfm1)
check("Upload -> msg=added", "msg=added" in loc(r),
      f"{r.status_code} {loc(r)}")

row = sqlite3.connect(DB).execute(
    "SELECT name, filename, version, vendor, source, description FROM modules "
    "WHERE name = 'Drittanbieter Test'").fetchone()
check("DB-Zeile source=third_party", row and row[4] == "third_party", str(row))
check("DB: Filename aus Name+Version", row and row[1] == "Drittanbieter_Test_v7.sfm", str(row))
check("DB: Version + Vendor aus Descriptor", row and row[2] == "7" and row[3] == "Fremd GmbH", str(row))
check("Datei in <data>/modules", os.path.isfile(os.path.join(DATA_MOD, "Drittanbieter_Test_v7.sfm")))
mm = manifest_modules()
check("versions.json enthält Drittanbieter",
      "Drittanbieter Test" in mm and mm["Drittanbieter Test"][0]["moduleVersion"] == "7",
      str(list(mm.keys())))
ev = sqlite3.connect(DB).execute(
    "SELECT action, detail FROM events WHERE action = 'module_add'").fetchall()
check("Event module_add", any("Drittanbieter Test" in d for _, d in ev), str(ev))

mod_id = sqlite3.connect(DB).execute(
    "SELECT id FROM modules WHERE name = 'Drittanbieter Test'").fetchone()[0]

# --- 8. Download der Drittanbieter-Datei (aus <data>/modules) ---------------
r = c.get(f"/admin/modules/{mod_id}/download?cache=0")
check("Download Drittanbieter -> 200 + Inhalt",
      r.status_code == 200 and r.content == open(sfm1, "rb").read(),
      f"{r.status_code} {len(r.content)}B")

# --- 3. SOLL-Erwartungen enthalten Drittanbieter -----------------------------
exp = monitoring._module_expectations()
tp = exp.get("Drittanbieter Test")
check("_module_expectations enthält Drittanbieter",
      tp is not None and tp["source"] == "third_party" and tp["version"] == 7,
      str(tp))
check("Eigene Module source='own'", exp.get("CallBlocker", {}).get("source") == "own",
      str(exp.get("CallBlocker")))

# --- 6. Monitoring-Filter -----------------------------------------------------
raw_empty = "[]"
items_off = monitoring._compare_modules(exp, raw_empty)
items_on = monitoring._compare_modules(exp, raw_empty, filter_third_party_missing=True)
tp_off = [it for it in items_off if it["name"] == "Drittanbieter Test"]
tp_on = [it for it in items_on if it["name"] == "Drittanbieter Test"]
own_off = [it for it in items_off if it["name"] == "CallBlocker"]
own_on = [it for it in items_on if it["name"] == "CallBlocker"]
check("Ohne Filter: Drittanbieter als missing", tp_off and tp_off[0]["status"] == "missing", str(tp_off))
check("Mit Filter: Drittanbieter (nicht installiert) ausgeblendet", not tp_on,
      str([it["name"] for it in items_on]))
check("Filter lässt eigene Module unberührt",
      own_off and own_on and own_on[0]["status"] == "missing", str(own_on))
raw_installed = json.dumps([{"id": 1, "name": "Drittanbieter Test", "version": 7,
                             "vendor": "Fremd GmbH",
                             "instances": [{"name": "Inst", "disabled": False}]}])
items_inst = monitoring._compare_modules(exp, raw_installed,
                                         filter_third_party_missing=True)
tp_inst = [it for it in items_inst if it["name"] == "Drittanbieter Test"]
check("Mit Filter + installiert: Drittanbieter sichtbar",
      len(tp_inst) == 1 and tp_inst[0]["status"] == "ok" and tp_inst[0]["source"] == "third_party",
      str(tp_inst))

# --- 4. Fehlerfälle -----------------------------------------------------------
bad = "/tmp/third_party_modules_test/keinzip.sfm"
with open(bad, "w", encoding="utf-8") as fh:
    fh.write("das ist kein zip-archiv")
r = upload(c, bad)
check("Ungültige .sfm -> err=invalid", "err=invalid" in loc(r),
      f"{r.status_code} {loc(r)}")

r = c.post("/admin/modules/third-party",
           files={"module_file": ("doc.txt", io.BytesIO(b"hello"), "text/plain")})
check("Falsche Endung -> err=not_sfm", "err=not_sfm" in loc(r),
      f"{r.status_code} {loc(r)}")

coll = "/tmp/third_party_modules_test/kollision.sfm"
make_sfm(coll, "CallBlocker", "99", vendor="Böser Hacker")
r = upload(c, coll)
check("Kollision mit eigenem Modul -> err=exists", "err=exists" in loc(r),
      f"{r.status_code} {loc(r)}")
check("Eigenes Modul unangetastet",
      sqlite3.connect(DB).execute(
          "SELECT version, source FROM modules WHERE name = 'CallBlocker'").fetchone() == cb_before,
      str(sqlite3.connect(DB).execute(
          "SELECT version, source FROM modules WHERE name = 'CallBlocker'").fetchone()))

# --- 5. Aktualisierung (gleicher Name, neue Version) --------------------------
sfm2 = "/tmp/third_party_modules_test/drittanbieter_v8.sfm"
make_sfm(sfm2, "Drittanbieter Test", "8", vendor="Fremd GmbH",
         description="Ein fremdes Testmodul v8")
r = upload(c, sfm2)
check("Upload gleicher Name -> msg=updated", "msg=updated" in loc(r),
      f"{r.status_code} {loc(r)}")
row = sqlite3.connect(DB).execute(
    "SELECT filename, version FROM modules WHERE name = 'Drittanbieter Test'").fetchone()
check("DB auf v8 aktualisiert", row and row[0] == "Drittanbieter_Test_v8.sfm" and row[1] == "8", str(row))
check("Alte Datei entfernt", not os.path.exists(os.path.join(DATA_MOD, "Drittanbieter_Test_v7.sfm")))
check("Neue Datei vorhanden", os.path.isfile(os.path.join(DATA_MOD, "Drittanbieter_Test_v8.sfm")))
mm = manifest_modules()
check("versions.json nur v8", mm["Drittanbieter Test"][0]["moduleVersion"] == "8",
      str(mm.get("Drittanbieter Test")))
ev = sqlite3.connect(DB).execute(
    "SELECT action, detail FROM events WHERE action = 'module_update'").fetchall()
check("Event module_update", any("v8" in d for _, d in ev), str(ev))

# --- 7. Seiten rendern ---------------------------------------------------------
r = c.post("/admin/installations", data={
    "name": "Testanlage", "url": "https://anlage.example",
    "auth_id": "", "auth_pass": "", "client_secret": "", "is_starface10": "1"})
check("Test-Anlage angelegt", r.status_code in (200, 303), f"{r.status_code}")

r = c.get("/admin/modules")
check("Modul-Seite -> 200 + zwei Tabellen",
      r.status_code == 200 and "Verfügbare Module" in r.text and "Drittanbietermodule" in r.text,
      f"{r.status_code}")
check("Upload-Formular + Löschen sichtbar",
      'action="/admin/modules/third-party"' in r.text and "Hochladen" in r.text and "Löschen" in r.text)
check("Drittanbieter in Tabelle", "Drittanbieter Test" in r.text)
check("Eigene Module in Tabelle", "CallBlocker" in r.text)

r = c.get("/admin/updates?inst_id=1")
exp_keys = list(monitoring._module_expectations().keys())
check("Update-Seite -> 200", r.status_code == 200, f"{r.status_code}")
check("Update-Seite: SOLL enthält Drittanbieter", "Drittanbieter Test" in exp_keys, str(exp_keys))
check("Update-Seite: Name gerendert", "Drittanbieter Test" in r.text,
      f"name fehlt; len={len(r.text)}")
check("Update-Seite: Badge Drittanbieter", "Drittanbieter" in r.text, "badge fehlt")
check("Update-Seite: v8", "v8" in r.text, "version fehlt")
check("Update-Seite: eigene Module bleiben", "CallBlocker" in r.text)

# --- 9. Löschen ------------------------------------------------------------------
r = c.post(f"/admin/modules/third-party/{mod_id}/delete")
check("Delete -> msg=deleted", "msg=deleted" in loc(r),
      f"{r.status_code} {loc(r)}")
check("DB-Zeile gelöscht", sqlite3.connect(DB).execute(
    "SELECT COUNT(*) FROM modules WHERE name = 'Drittanbieter Test'").fetchone()[0] == 0)
check("Datei entfernt", not os.path.exists(os.path.join(DATA_MOD, "Drittanbieter_Test_v8.sfm")))
mm = manifest_modules()
check("versions.json ohne Drittanbieter", "Drittanbieter Test" not in mm, str(list(mm.keys())))
ev = sqlite3.connect(DB).execute(
    "SELECT action, detail FROM events WHERE action = 'module_delete'").fetchall()
check("Event module_delete", any("Drittanbieter Test" in d for _, d in ev), str(ev))
exp2 = monitoring._module_expectations()
check("SOLL ohne gelöschten Drittanbieter", "Drittanbieter Test" not in exp2, str(list(exp2.keys())))
r = c.get("/admin/modules")
check("Modul-Seite nach Delete ohne Drittanbieter", "Drittanbieter Test" not in r.text)

print()
if FAIL:
    print(f"FEHLGESCHLAGEN: {len(FAIL)} → {', '.join(FAIL)}")
    sys.exit(1)
print("ALLE BESTANDEN")
