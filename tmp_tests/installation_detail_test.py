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
NO_DEPLOY = json.dumps([
    {"name": "CallBlocker", "version": 28, "vendor": "MiCoSa79", "instances": []},
    {"name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False}]},
])

real_xmlrpc = monitoring._xmlrpc

_CALLS = []


def fake_xmlrpc(url, token, method, params=None, instance_name=None):
    if url == "http://net":
        raise ConnectionError("no route to host")
    if method == "GetStats":
        return {"members": {"systemName": "pbx", "systemVersion": "10.0.2.5", "providerStatus": ""}}
    if method == "GetModuleStatus":
        data = INSTALLED_OK if url == "http://ok" else NO_DEPLOY
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
    raise AssertionError(method)


monitoring._xmlrpc = fake_xmlrpc
monitoring.MODULES_DIR = MODDIR
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}
import module_updates  # noqa: E402
module_updates._xmlrpc = fake_xmlrpc  # from-Import-Kopie separat mocken!
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
    _saved = INSTALLED_OK
    _noact = json.loads(INSTALLED_OK)
    _noact[0]["instances"][0]["disabled"] = True
    INSTALLED_OK = json.dumps(_noact)
    r = c.get("/installation/1")
    body2 = r.text
    check("Detail: ohne aktive Instanz -> KEIN Blocklist-Button, nur Badge (F70)",
          "Keine aktive Instanz" in body2 and "Blocklist bearbeiten" not in body2)
    check("Detail: Instanz-anlegen-Button sichtbar ohne aktive Instanz (F79)",
          ">Instanz anlegen</button>" in body2 and "Instanzname" in body2
          and "id=\"dlg-instance\"" in body2)
    INSTALLED_OK = _saved

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
