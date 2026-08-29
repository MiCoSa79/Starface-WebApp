#!/usr/bin/env python3
"""Tests für F67: Anlagen-Detail-Seite /installation/{id} + Deployment-Modul-Test.

Geprüft werden:
1. _deployment_modul_status: ok / not-installed / no-active-instance / config / unreachable
2. Route GET /installation/{id}: 200 für Admin, Stammdaten-Karte, Modul-Status-Karte
   (inkl. Deployment-Modul-Badge), Einstellungen-Spalte in der Tabelle (CallBlocker ->
   Blocklist-Button NUR wenn installiert UND Instanz aktiv),
   Redirects (ohne Login, unbekannte Anlage)
3. Route GET /installation/{id}/test: Deployment-Check-Ergebnis als JSON
4. Anlagen-Übersicht: „Zur Anlage“-Button statt Blocklist-Button
"""
import json
import os
import sys
import tempfile
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "app"))

MODDIR = os.path.join(os.path.dirname(__file__), "module_status_fakes")
os.makedirs(MODDIR, exist_ok=True)
os.environ["MODULES_DIR"] = MODDIR  # vor dem monitoring-Import


def make_sfm(path, name, version, vendor="MiCoSa79", rpcs=()):
    rpc_xml = ""
    if rpcs:
        rpc_xml = "<entryPoints>" + "".join(
            f'<rpcEntryPoint name="{r}"><type>XMLRPC_auth</type></rpcEntryPoint>'
            for r in rpcs) + "</entryPoints>"
    desc = (f"<?xml version='1.0' encoding='UTF-8'?>\n<module id=\"uuid-{name}\" "
            f"name=\"{name}\" specVersion=\"5\" vendor=\"{vendor}\" version=\"{version}\">"
            f"<noLicenseId>x</noLicenseId>{rpc_xml}</module>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("META-INF/MANIFEST.MF",
                   f"Manifest-Version: 1.0\r\nObjectId: uuid-{name}\r\nStarfaceModule_SpecVersion: 5\r\n")
        z.writestr("module-descriptor.xml", desc)


for f in os.listdir(MODDIR):
    os.remove(os.path.join(MODDIR, f))
make_sfm(os.path.join(MODDIR, "CallBlocker.sfm"), "CallBlocker", 28)
make_sfm(os.path.join(MODDIR, "TelefonieMonitoring.sfm"), "TelefonieMonitoring", 5,
         rpcs=("GetStats", "GetModuleStatus"))
make_sfm(os.path.join(MODDIR, "Deployment-Modul.sfm"), "Deployment-Modul", 1)

_tmpdb = tempfile.mktemp(suffix=".db", prefix="starface_detail_")
os.environ["STARFACE_DB"] = _tmpdb
from cryptography.fernet import Fernet  # noqa: E402
os.environ["FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "pw123"
os.environ["APP_VERSION"] = "v1.0.59-test"

import main  # noqa: E402
import monitoring  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def login(c, u, p):
    r = c.post("/api/login", data={"username": u, "password": p})
    return r.status_code == 200 and r.json().get("status") == "ok"


INSTALLED_OK = json.dumps([
    {"id": "a", "name": "CallBlocker", "version": 28, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
    {"id": "b", "name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
    {"id": "c", "name": "Deployment-Modul", "version": 9, "vendor": "MiCoSa79",
     "instances": [{"name": "Deployer", "disabled": False}]},
])
# F82: Deployment-Modul nur v8 installiert -> CreateInstance-RPC existiert nicht,
# der „Instanz anlegen“-Button darf dann nicht erscheinen.
INSTALLED_OK_DM8 = json.dumps([
    {"id": "a", "name": "CallBlocker", "version": 28, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
    {"id": "b", "name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
    {"id": "c", "name": "Deployment-Modul", "version": 8, "vendor": "MiCoSa79",
     "instances": [{"name": "Deployer", "disabled": False}]},
])
# F83: CallBlocker ist veraltet (v27 < SOLL 28) -> Update verfügbar -> Aktualisieren-Button
INSTALLED_OUTDATED = json.dumps([
    {"id": "a", "name": "CallBlocker", "version": 27, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
    {"id": "b", "name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
    {"id": "c", "name": "Deployment-Modul", "version": 9, "vendor": "MiCoSa79",
     "instances": [{"name": "Deployer", "disabled": False}]},
])
NO_DEPLOY = json.dumps([
    {"name": "CallBlocker", "version": 28, "vendor": "MiCoSa79", "instances": []},
    {"name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
])

real_xmlrpc = monitoring._xmlrpc

_CALLS = []


_FAKE_INSTALLED = INSTALLED_OK  # F82: Tests können auf DM-v8-Zustand umschalten


def fake_xmlrpc(url, token, method, params=None, instance_name=None):
    if url == "http://net":
        raise ConnectionError("no route to host")
    if method == "GetStats":
        return {"members": {"systemName": "pbx", "systemVersion": "10.0.2.5", "providerStatus": ""}}
    if method == "GetModuleStatus":
        data = _FAKE_INSTALLED if url == "http://ok" else NO_DEPLOY
        return {"members": {"moduleJson": data}}
    if method == "CreateInstance":
        _CALLS.append({"method": method, "params": dict(params or {}),
                       "instance_name": instance_name, "url": url})
        if (params or {}).get("instanceName") == "FehlerFall":
            txt = "ERROR: Instanz existiert bereits: FehlerFall"
        else:
            txt = "OK: Instanz angelegt und aktiviert"
        return {"raw": f'<?xml version="1.0"?><methodResponse><params><param><value><struct><member><name>response</name><value><string>{txt}</string></value></member></struct></value></param></params></methodResponse>',
                "values": [txt], "members": {"response": txt}}
    if method == "UpdateFromUrl":
        _CALLS.append({"method": method, "params": dict(params or {}),
                       "instance_name": instance_name, "url": url})
        return {"raw": "<methodResponse>ok</methodResponse>", "values": ["imported"]}
    raise AssertionError(method)


monitoring._xmlrpc = fake_xmlrpc
monitoring.MODULES_DIR = MODDIR
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}
import module_updates  # noqa: E402
module_updates._xmlrpc = fake_xmlrpc  # from-Import-Kopie separat mocken!
# F83: Update-Kanal für signierte Update-URLs (Env live von _module_update_base gelesen)
os.environ["MODULE_UPDATE_BASE_URL"] = "https://modulupdates.example"
os.environ["UPDATE_SIGNING_SECRET"] = "f83-secret"
main._get_token = lambda inst: "tok123"  # OAuth-Erwerb im Test überspringen

# ── 1. _deployment_modul_status (Unit) ───────────────────────────────────

def full_inst(**kw):
    base = {"url": "http://ok", "name": "PBX", "auth_id": "a", "auth_pass": "p",
            "client_secret": "", "is_starface10": 1, "oauth_client": "", "oauth_access": "",
            "oauth_refresh": "", "oauth_expires": 0, "module_instance_name": "CallBlocker",
            "monitoring_instance_name": "TelefonieMonitoring",
            "deployer_instance_name": "Deployer", "deployer_token": "tok123"}
    base.update(kw)
    return base


ok_inst = full_inst()
no_deploy = full_inst(url="http://hmm")
no_mon = full_inst(monitoring_instance_name="")
net_inst = full_inst(url="http://net")

r = main._deployment_modul_status(ok_inst)
check("deploy: ok + aktive Instanz", r["ok"] and r["state"] == "ok"
      and "Deployment-Modul installiert und erreichbar" in r["message"] and "Deployer" in r["message"],
      json.dumps(r, ensure_ascii=False))

r = main._deployment_modul_status(no_deploy)
check("deploy: Modul nicht installiert -> not-installed", not r["ok"] and r["state"] == "not-installed",
      json.dumps(r, ensure_ascii=False))

r = main._deployment_modul_status(no_mon)
check("deploy: keine Monitoring-Instanz -> config", not r["ok"] and r["state"] == "config",
      json.dumps(r, ensure_ascii=False))

r = main._deployment_modul_status(net_inst)
check("deploy: Verbindungsfehler -> unreachable", not r["ok"] and r["state"] == "unreachable",
      json.dumps(r, ensure_ascii=False))

# ── 2. Routen (TestClient) ───────────────────────────────────────────────
with TestClient(main.app) as c:
    c.follow_redirects = False

    conn = main._db()
    conn.execute("INSERT INTO installations (name, url, module_instance_name, monitoring_instance_name, "
                 "deployer_instance_name, deployer_token, is_starface10) "
                 "VALUES ('Testanlage A', 'http://ok', 'CallBlocker', 'TelefonieMonitoring', "
                 "'Deployer', 'tok123', 1)")
    conn.commit()
    conn.close()

    r = c.get("/installation/1")
    check("ohne Login: /installation/1 -> Redirect /", r.status_code in (303, 307)
          and r.headers.get("location", "").rstrip("/") == "", f"{r.status_code} {r.headers.get('location')}")

    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "CallBlocker"})
    check("POST instance ohne Login -> Redirect / (F79)", r.status_code in (303, 307)
          and r.headers.get("location", "").rstrip("/") == "", f"{r.status_code} {r.headers.get('location')}")

    check("Login admin", login(c, "admin", "pw123"))

    r = c.get("/installation/1")
    body = r.text
    check("Detail: 200 + Stammdaten-Karte", r.status_code == 200 and "Anlage: Testanlage A" in body
          and "Stammdaten" in body and "http://ok" in body, str(r.status_code))
    check("Stammdaten: Anlagen-Version + Deployment-Status + Token (F71)",
          "Anlagen-Version" in body and "10.0.2.5" in body
          and "Deployment-Modul" in body and "installiert und aktiv" in body
          and "Update-Token" in body and "gesetzt" in body
          and "CallBlocker-Instanz" not in body and "TelefonieMonitoring-Instanz" not in body)
    check("Detail: Modul-Status-Karte mit Deployment-Modul",
          "Modul-Status" in body and "Deployment-Modul" in body and "Aktuell" in body)
    check("Detail: Einstellungen-Spalte mit Blocklist-Button (installiert+aktiv, F70)",
          "<th>Einstellungen</th>" in body and "/installation/1/blocklist" in body
          and "Blocklist bearbeiten" in body and "Modul-Einstellungen" not in body)
    check("Detail: sein eigener Einstellungs-Button in der CallBlocker-Zeile (installiert+aktiv)",
          body.count("Blocklist bearbeiten") == 1)
    check("Detail: KEIN Instanz-anlegen-Button bei aktiven Instanzen (F79)",
          ">Instanz anlegen</button>" not in body)

    # CallBlocker-Instanz deaktivieren -> kein Einstellungs-Button (keine aktive Instanz)
    _saved = _FAKE_INSTALLED
    _noact = json.loads(_FAKE_INSTALLED)
    _noact[0]["instances"][0]["disabled"] = True
    _FAKE_INSTALLED = json.dumps(_noact)
    r = c.get("/installation/1")
    body2 = r.text
    check("Detail: ohne aktive Instanz -> KEIN Blocklist-Button, nur Badge (F70)",
          "Keine aktive Instanz" in body2 and "Blocklist bearbeiten" not in body2)
    check("Detail: Instanz-anlegen-Button sichtbar ohne aktive Instanz (F79)",
          ">Instanz anlegen</button>" in body2 and "Instanzname" in body2
          and "id=\"dlg-instance\"" in body2)
    _FAKE_INSTALLED = _saved

    # F79: POST /installation/{id}/instance — Instanz via Deployment-Modul anlegen
    _CALLS.clear()
    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "CallBlocker"})
    d = r.json()
    check("POST instance: ok + CreateInstance-RPC mit moduleName/instanceName (F79)",
          r.status_code == 200 and d.get("ok") is True and "angelegt" in d.get("message", "")
          and len(_CALLS) == 1
          and _CALLS[0]["params"] == {"moduleName": "CallBlocker", "instanceName": "CallBlocker"}
          and _CALLS[0]["instance_name"] == "Deployer"
          and _CALLS[0]["method"] == "CreateInstance",
          json.dumps({"status": r.status_code, "d": d, "calls": _CALLS}, ensure_ascii=False))

    # ── F80: eigene Module hinterlegen den Instanznamen automatisch als RPC-Zielfeld ──
    check("Detail: Button trägt data-field (CallBlocker -> module_instance_name, F80)",
          'data-field="module_instance_name"' in body2 and 'id="dlg-instance-rpc"' in body2)

    conn = main._db()
    r0 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()

    _CALLS.clear()
    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "CallBlocker-Neu"})
    d = r.json()
    check("F80: CallBlocker-Instanz ok + Meldung erwähnt RPC-Zielfeld",
          r.status_code == 200 and d.get("ok") is True and "RPC-Zielfeld" in d.get("message", ""),
          json.dumps(d, ensure_ascii=False))
    conn = main._db()
    r1 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()
    check("F80: CallBlocker -> module_instance_name gesetzt (Monitoring/Deployer unverändert)",
          r1 == {"module_instance_name": "CallBlocker-Neu",
                 "monitoring_instance_name": r0["monitoring_instance_name"],
                 "deployer_instance_name": r0["deployer_instance_name"]},
          json.dumps(r1, ensure_ascii=False))

    r = c.post("/installation/1/instance", json={"module": "TelefonieMonitoring", "name": "TelefonieMonitoring-I2"})
    d = r.json()
    check("F80: TelefonieMonitoring-Instanz ok", r.status_code == 200 and d.get("ok") is True,
          json.dumps(d, ensure_ascii=False))
    conn = main._db()
    r2 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()
    check("F80: TelefonieMonitoring -> monitoring_instance_name gesetzt (Rest unverändert)",
          r2["monitoring_instance_name"] == "TelefonieMonitoring-I2"
          and r2["module_instance_name"] == "CallBlocker-Neu"
          and r2["deployer_instance_name"] == r0["deployer_instance_name"],
          json.dumps(r2, ensure_ascii=False))

    r = c.post("/installation/1/instance", json={"module": "Deployment-Modul", "name": "Deployer2"})
    d = r.json()
    check("F80: Deployment-Modul-Instanz ok", r.status_code == 200 and d.get("ok") is True,
          json.dumps(d, ensure_ascii=False))
    conn = main._db()
    r3 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()
    check("F80: Deployment-Modul -> deployer_instance_name gesetzt",
          r3["deployer_instance_name"] == "Deployer2", json.dumps(r3, ensure_ascii=False))

    # Fremdes Modul (keine Zuordnung) -> RPC ok, aber KEIN Feld-Update
    _CALLS.clear()
    r = c.post("/installation/1/instance", json={"module": "Fremdmodul", "name": "Fremdmodul"})
    d = r.json()
    conn = main._db()
    r4 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()
    check("F80: Fremdmodul ok + kein Feld-Update",
          r.status_code == 200 and d.get("ok") is True and r4 == r3,
          json.dumps({"d": d, "r4": r4}, ensure_ascii=False))

    # RPC-Fehler -> KEIN Feld-Update
    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "FehlerFall"})
    d = r.json()
    conn = main._db()
    r5 = dict(conn.execute("SELECT module_instance_name, monitoring_instance_name, deployer_instance_name "
                           "FROM installations WHERE id=1").fetchone())
    conn.close()
    check("F80: RPC-Fehler -> kein Feld-Update",
          d.get("ok") is False and r5 == r4,
          json.dumps({"d": d, "r5": r5}, ensure_ascii=False))

    # ── F82: Aktionen auf der Detailseite (Auge / ⚡ Test / ✎ Edit) + DM-v8-Schutz ──
    r = c.get("/installation/1")
    body = r.text
    check("F82: Detail-Monitoring-Auge (detail-dl + /monitoring/installations/1)",
          'class="detail-dl"' in body and "/monitoring/installations/1" in body)
    check("F82: ⚡ Test-Button fürs Deployment-Modul (Admin -> testConn)",
          "testConn(1, 'Testanlage A', true)" in body and "Verbindung testen" in body,
          "testConn-Button fehlt")
    check("F82: ✎ Edit-Button (Admin -> Edit-Seite)",
          "/admin/installations/1/edit" in body and "Edit" in body,
          "Edit-Link fehlt")

    # F82: DM v8 (CB-Instanz deaktiviert -> „ohne aktive Instanz“) -> KEIN Button, Hinweis statt dessen
    _d8 = json.loads(INSTALLED_OK_DM8)
    _d8[0]["instances"][0]["disabled"] = True
    _FAKE_INSTALLED = json.dumps(_d8)
    r = c.get("/installation/1")
    body8 = r.text
    check("F82: DM v8 -> KEIN inst-create-Button + Hinweis 'DM v9 nötig'",
          "inst-create" not in body8 and "DM v9 nötig" in body8,
          "inst-create im Body: " + str("inst-create" in body8),
          )
    # F82: zurück auf DM v9 (CB weiter deaktiviert) -> Button wieder da
    _d9 = json.loads(INSTALLED_OK)
    _d9[0]["instances"][0]["disabled"] = True
    _FAKE_INSTALLED = json.dumps(_d9)
    r = c.get("/installation/1")
    check("F82: DM v9 (zurückgeschaltet) -> inst-create-Button wieder da",
          "inst-create" in r.text and "DM v9 nötig" not in r.text,
          "Umschalt-Mechanik defekt")
    _FAKE_INSTALLED = INSTALLED_OK

    # ── F83: Modul-Aktualisierung direkt von der Detailseite ──
    r = c.get("/installation/1")
    body_ok = r.text
    check("F83: aktuell (ok) -> KEIN Aktualisieren-Button",
         "Aktualisieren" not in body_ok, "Button trotz aktueller Version?")
    _FAKE_INSTALLED = INSTALLED_OUTDATED
    r = c.get("/installation/1")
    body_u = r.text
    check("F83: outdated-Zeile -> Aktualisieren-Button",
         "⬆ Aktualisieren" in body_u and "updateModuleInst(1, this)" in body_u
         and 'data-module="CallBlocker"' in body_u,
         "Button fehlt in der outdated-Zeile?")
    _CALLS.clear()
    r = c.post("/installation/1/module/update", json={"module": "CallBlocker"})
    _j = None
    try:
       _j = r.json()
    except Exception:
       _j = {"raw": r.text[:200]}
    check("F83: POST ok + UpdateFromUrl-RPC (Deployer-Instanz)",
         r.status_code == 200 and (_j or {}).get("ok") is True
         and any(x.get("method") == "UpdateFromUrl"
                 and "CallBlocker" in str(x.get("params"))
                 for x in _CALLS),
         json.dumps({"st": r.status_code, "j": _j,
                     "calls": [x.get("method") for x in _CALLS[-3:]]},
                    ensure_ascii=False))
    r = c.post("/installation/1/module/update", json={"module": "   "})
    check("F83: leerer Modulname -> 400", r.status_code == 400)
    _FAKE_INSTALLED = INSTALLED_OK
    c.cookies.clear()
    r = c.post("/installation/1/module/update", json={"module": "CallBlocker"})
    check("F83: ohne Login -> 403", r.status_code == 403)
    login(c, "admin", "pw123")
    # Anlage kurz auf unerreichbare URL schalten (passiert live bei Netz-/OAuth-Fehlern)
    _db2 = main._db()
    _db2.execute("UPDATE installations SET url='http://net' WHERE id=1")
    _db2.commit()
    _db2.close()
    r = c.post("/installation/1/module/update", json={"module": "CallBlocker"})
    _j = r.json() if "json" in r.headers.get("content-type", "") else {}
    check("F83: Anlage nicht erreichbar -> ok:false + Meldung",
          r.status_code == 200 and _j.get("ok") is False and len(_j.get("msg", "")) > 0,
          json.dumps(_j, ensure_ascii=False))
    _db3 = main._db()
    _db3.execute("UPDATE installations SET url='http://ok' WHERE id=1")
    _db3.commit()
    _db3.close()

    # ── F84: Blocklist-Zurück führt zur Detailseite, nicht zur Übersicht ──
    r = c.get("/installation/1/blocklist")
    check("F84: Blocklist-Zurück -> Detailseite (/installation/1)",
         r.status_code == 200
         and '<a href="/installation/1" class="btn-secondary btn-back">' in r.text,
         "Zurück-Link zeigt noch auf die Übersicht? " + r.text[r.text.find("btn-back")-80:r.text.find("btn-back")+120])


    _FAKE_INSTALLED = INSTALLED_OK

    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "FehlerFall"})
    d = r.json()
    check("POST instance: Modul-Fehler -> ok:false mit Modul-Meldung (F79)",
          r.status_code == 502 and d.get("ok") is False and "existiert bereits" in d.get("error", ""),
          json.dumps({"status": r.status_code, "d": d}, ensure_ascii=False))

    r = c.post("/installation/1/instance", json={"module": "", "name": "x"})
    check("POST instance: module leer -> 400 (F79)", r.status_code == 400)

    r = c.post("/installation/1/instance", json={"module": "CallBlocker", "name": "   "})
    check("POST instance: Instanzname leer -> 400 (F79)", r.status_code == 400)

    r = c.post("/installation/99/instance", json={"module": "CallBlocker", "name": "x"})
    check("POST instance: unbekannte Anlage -> 404 (F79)", r.status_code == 404)

    r = c.get("/installation/1/test")
    d = r.json()
    check("Test-API: ok + state ok", d.get("ok") is True and d.get("state") == "ok",
          json.dumps(d, ensure_ascii=False))

    r = c.get("/installation/99")
    check("Detail: unbekannte Anlage -> Redirect /anlagen", r.status_code in (303, 307)
          and "/anlagen" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")

    r = c.get("/anlagen")
    body = r.text
    check("Anlagen-Übersicht: „Zur Anlage“ statt Blocklist-Button",
          "Zur Anlage" in body and "/installation/1" in body and "/blocklist" not in body)
    check("Tabelle: Auge-Link (Detail-Monitoring) VOR „Zur Anlage“ (F69)",
          "Detail-Monitoring der Anlage" in body
          and body.index("/monitoring/installations/1") < body.index('href="/installation/1"'))

    # Admin-Test-Button-Endpunkt (test-conn) liefert ebenfalls den Deployment-Check
    r = c.get("/admin/installations/1/test-conn")
    d = r.json()
    check("Admin test-conn: ok + Deployment-Meldung",
          d.get("ok") is True and "Deployment-Modul" in d.get("message", ""),
          json.dumps(d, ensure_ascii=False))

    # F68/F69: Edit-Seite — Zurück-Button oben; das Auge wandert in die Tabellen-Zeile (F69)
    r = c.get("/admin/installations/1/edit")
    body = r.text
    check("Edit-Seite: 200 + Zurück-Button oben",
          r.status_code == 200 and "Zurück zur Anlagen-Übersicht" in body
          and 'href="/anlagen"' in body)
    check("Edit-Seite: KEIN Auge-Link zur Monitoring-Detailseite (F69)",
          f"/monitoring/installations/1" not in body)
    # F68: einheitliche Button-Optik in der Tabellen-Zeile (keine Inline-Style-Reste)
    r = c.get("/anlagen")
    body = r.text
    check("Tabelle: einheitliche Buttons ohne Inline-Styles",
          'class="btn-secondary"' in body and "style=\"font-size:13px" not in body)

monitoring._xmlrpc = real_xmlrpc
module_updates._xmlrpc = real_xmlrpc

print()
if FAIL:
    print(f"❌ {len(FAIL)} FAIL(s): {', '.join(FAIL)}")
    sys.exit(1)
print("✅ Alle Checks bestanden.")
