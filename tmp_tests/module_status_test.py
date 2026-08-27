"""Tests für den Modul-Status-Abgleich (TelefonieMonitoring v5 GetModuleStatus).

Geprüft werden:
1. _module_expectations: SOLL-Module aus app/modules/*.sfm (mtime-Cache, kaputte Dateien)
2. _compare_modules: IST/SOLL-Vergleich (ok / outdated / missing, Instanz-Status, Fehlerantworten)
3. _classify_error: Fehlerkategorien (unreachable / module / error)
4. _collect_module_status: GetModuleStatus-Poll inkl. „Modul zu alt“-Fall
5. collect_installations komplett (echte DB, gemockter XML-RPC): modules-State je Anlage + last_error.category
6. Render-Test monitoring.html: Modul-Karte, Badges, Hinweise, errbox-warn
"""
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ.setdefault("STARFACE_DB", "/tmp/module_status_test.db")
os.environ.setdefault("APP_VERSION", "v9.9.9-TEST")

FAIL = []

def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)

# ---------------------------------------------------------------- Vorbereitung
MODDIR = os.path.join(os.path.dirname(__file__), "module_status_fakes")
os.makedirs(MODDIR, exist_ok=True)
os.environ["MODULES_DIR"] = MODDIR  # VOR dem Import — monitoring liest beim Laden

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
with open(os.path.join(MODDIR, "kaputt.sfm"), "w") as f:  # keine JAR — muss ignoriert werden
    f.write("kein zip")

import monitoring

# ------------------------------------------------- 1. _module_expectations
exp = monitoring._module_expectations()
check("expectations: beide echten Module gelesen",
      set(exp) == {"CallBlocker", "TelefonieMonitoring"}, str(sorted(exp)))
check("expectations: CallBlocker v28 + Vendor", exp["CallBlocker"]["version"] == 28
      and exp["CallBlocker"]["vendor"] == "MiCoSa79", str(exp.get("CallBlocker")))
check("expectations: TelefonieMonitoring v5 (Fakes)", exp["TelefonieMonitoring"]["version"] == 5,
      str(exp.get("TelefonieMonitoring")))
check("expectations: nur TelefonieMonitoring exportiert GetModuleStatus",
      "GetModuleStatus" in exp["TelefonieMonitoring"].get("provides", [])
      and "GetModuleStatus" not in exp["CallBlocker"].get("provides", []),
      str({k: v.get("provides") for k, v in exp.items()}))
check("expectations: kaputte .sfm ignoriert", "kaputt" not in exp)

exp2 = monitoring._module_expectations()
check("expectations: Cache (gleiche Signatur -> gleiches Objekt)", exp2 is exp)

# mtime-Änderung -> Neu-Parse (Release-Szenario)
make_sfm(os.path.join(MODDIR, "CallBlocker.sfm"), "CallBlocker", 29)
t = time.time() + 5; os.utime(os.path.join(MODDIR, "CallBlocker.sfm"), (t, t))
exp3 = monitoring._module_expectations()
check("expectations: mtime-Change -> neue Version 29", exp3["CallBlocker"]["version"] == 29,
      str(exp3.get("CallBlocker")))
make_sfm(os.path.join(MODDIR, "CallBlocker.sfm"), "CallBlocker", 28)  # zuruecksetzen

# echtes app/modules (Single Source of Truth im Repo)
real_dir = os.path.join(os.path.dirname(__file__), "..", "app", "modules")
rollback = monitoring.MODULES_DIR
monitoring.MODULES_DIR = real_dir
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}
real_exp = monitoring._module_expectations()
monitoring.MODULES_DIR = rollback
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}
check("expectations: echtes app/modules -> CallBlocker v30 + TelefonieMonitoring v9",
      real_exp.get("CallBlocker", {}).get("version") == 30
      and real_exp.get("TelefonieMonitoring", {}).get("version") == 9,
      str(real_exp))

# ------------------------------------------------- 2. _compare_modules
INSTALLED_OK = json.dumps([
    {"id": "a", "name": "CallBlocker", "version": 28, "vendor": "MiCoSa79",
     "instances": [{"name": "CallBlocker", "disabled": False}]},
    {"id": "b", "name": "TelefonieMonitoring", "version": 5, "vendor": "MiCoSa79",
     "instances": [{"name": "TelefonieMonitoring", "disabled": False},
                   {"name": "Test-Instanz", "disabled": True}]},
])
items = monitoring._compare_modules(exp, INSTALLED_OK)
check("compare: 2 erwartete Module geprueft", len(items) == 2, str(len(items)))
by = {i["name"]: i for i in items}
check("compare: CallBlocker ok + aktuell + Instanz aktiv",
      by["CallBlocker"]["status"] == "ok" and by["CallBlocker"]["current"]
      and by["CallBlocker"]["version_ist"] == 28
      and by["CallBlocker"]["instances"] == [{"name": "CallBlocker", "active": True}],
      str(by["CallBlocker"]))
check("compare: TelefonieMonitoring Instanz-Status aktiv/deaktiviert",
      by["TelefonieMonitoring"]["instances"] == [
          {"name": "TelefonieMonitoring", "active": True},
          {"name": "Test-Instanz", "active": False}],
      str(by["TelefonieMonitoring"]["instances"]))

items = monitoring._compare_modules(exp, json.dumps([
    {"name": "CallBlocker", "version": 27, "vendor": "MiCoSa79", "instances": []},
]))
by = {i["name"]: i for i in items}
check("compare: CallBlocker outdated (27<28)",
      by["CallBlocker"]["status"] == "outdated" and not by["CallBlocker"]["current"]
      and by["CallBlocker"]["version_ist"] == 27 and by["CallBlocker"]["version_soll"] == 28,
      str(by["CallBlocker"]))
check("compare: TelefonieMonitoring missing (ohne Instanzen-Liste)",
      by["TelefonieMonitoring"]["status"] == "missing"
      and by["TelefonieMonitoring"]["version_ist"] is None, str(by["TelefonieMonitoring"]))
check("compare: CallBlocker ohne Instanzen -> leere Instanzliste",
      by["CallBlocker"]["instances"] == [], str(by["CallBlocker"]["instances"]))
check("compare: Modul-Fehlerantwort {\"error\"} -> None",
      monitoring._compare_modules(exp, '{"error":"boom"}') is None)
check("compare: unparsbar -> None", monitoring._compare_modules(exp, "kaputt") is None)
missing_all = monitoring._compare_modules(exp, "[]")
check("compare: leere Liste -> alle missing",
      missing_all is not None and all(i["status"] == "missing" for i in missing_all))
fremd = monitoring._compare_modules(exp, json.dumps([
    {"name": "FremdModul", "version": 1, "vendor": "x", "instances": []}]))
check("compare: fremde Module werden ignoriert (nur unsere geprueft)",
      fremd is not None and all(i["status"] == "missing" for i in fremd) and len(fremd) == 2)

# ------------------------------------------------- 3. _classify_error
cls = monitoring._classify_error(RuntimeError("STARFACE-Fehler: unknown method -> Modul fehlt"))
check("classify: XML-RPC-Fault -> module", cls["category"] == "module"
      and cls["msg"] == "Monitoring-Modul nicht installiert oder eingerichtet", str(cls))
try:
    import httpx
    cls = monitoring._classify_error(httpx.ConnectError("no route to host"))
    check("classify: httpx.ConnectError -> unreachable", cls["category"] == "unreachable", str(cls))
    cls = monitoring._classify_error(httpx.ReadTimeout("read timed out"))
    check("classify: httpx.ReadTimeout -> unreachable", cls["category"] == "unreachable", str(cls))
except ImportError:
    check("classify: httpx.ConnectError -> unreachable", False, "httpx fehlt")
cls = monitoring._classify_error(TimeoutError("timed out"))
check("classify: TimeoutError -> unreachable", cls["category"] == "unreachable", str(cls))
cls = monitoring._classify_error(ValueError("komischer Fehler"))
check("classify: sonstiger Fehler -> error", cls["category"] == "error", str(cls))

# ------------------------------------------------- 4. _collect_module_status
real_xmlrpc = monitoring._xmlrpc
FAULT_URL, OLD_URL, NET_URL = "http://fault", "http://old", "http://net"

def fake_xmlrpc(url, token, method, params=None, instance_name=None):
    if url == FAULT_URL:
        raise RuntimeError("STARFACE-Fehler: unknown method - Modul nicht installiert")
    if url == OLD_URL:
        raise RuntimeError("STARFACE-Fehler: unknown method GetModuleStatus")
    if url == NET_URL:
        raise ConnectionError("no route to host")
    if method == "GetStats":
        return {"members": {"systemName": "pbx", "systemVersion": "10.0.2.5", "providerStatus": ""}}
    if method == "GetModuleStatus":
        return {"members": {"moduleJson": INSTALLED_OK}}
    raise AssertionError(method)

monitoring._xmlrpc = fake_xmlrpc
inst_ok = {"url": "http://ok", "monitoring_instance_name": "TelefonieMonitoring"}
inst_fault = {"url": FAULT_URL, "monitoring_instance_name": "TelefonieMonitoring"}
inst_old = {"url": OLD_URL, "monitoring_instance_name": "TelefonieMonitoring"}
inst_net = {"url": NET_URL, "monitoring_instance_name": "TelefonieMonitoring"}

m = monitoring._collect_module_status(inst_ok, "tok", "PBX-1")
check("collect: Erfolg -> list + kein error", m["error"] is None and len(m["list"]) == 2, str(m)[:150])
m = monitoring._collect_module_status(inst_fault, "tok", "PBX-2")
msg_alt = (m.get("error") or {}).get("msg", "")
check("collect: GetModuleStatus-Fehler nach GetStats -> module (zu alt), Update-Ziel v5 (Fake-Modul)",
      m["error"] is not None and m["error"]["category"] == "module"
      and "zu alt" in msg_alt and "Update auf v5" in msg_alt
      and "v28" not in msg_alt, repr(msg_alt))
# Ohne provides (kein Modul exportiert GetModuleStatus) -> Meldung ohne Versions-Klammer
no_rpc_expected = {"CallBlocker": {"version": 28, "provides": []},
                   "TelefonieMonitoring": {"version": 5, "provides": []}}
mon_orig = monitoring._module_expectations
monitoring._module_expectations = lambda: no_rpc_expected
try:
    m2 = monitoring._collect_module_status(inst_fault, "tok", "PBX-2b")
finally:
    monitoring._module_expectations = mon_orig
msg2 = (m2.get("error") or {}).get("msg", "")
check("collect: zu alt ohne provides-Info -> kein Versions-Zusatz",
      "zu alt" in msg2 and "Update auf v" not in msg2, repr(msg2))
m = monitoring._collect_module_status(inst_net, "tok", "PBX-3")
check("collect: Verbindungsfehler -> unreachable", m["error"]["category"] == "unreachable", str(m["error"]))

monitoring._xmlrpc = lambda url, token, method, **kw: {"members": {"moduleJson": '{"error":"boom"}'}}
m = monitoring._collect_module_status(inst_ok, "tok", "PBX-4")
check("collect: Modul-Fehlerantwort -> error-Meldung",
      m["error"] is not None and "ausgewertet" in m["error"]["msg"], str(m["error"]))
monitoring._xmlrpc = real_xmlrpc

leer_dir = os.path.join(os.path.dirname(__file__), "module_status_leer")
os.makedirs(leer_dir, exist_ok=True)
for f in os.listdir(leer_dir):
    os.remove(os.path.join(leer_dir, f))
rollback = monitoring.MODULES_DIR
monitoring.MODULES_DIR = leer_dir
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}
m = monitoring._collect_module_status(inst_ok, "tok", "PBX-5")
check("collect: keine erwarteten Module -> list [] (keine Anzeige)", m["list"] == [], str(m))
monitoring.MODULES_DIR = rollback
monitoring._EXPECT_CACHE["sig"], monitoring._EXPECT_CACHE["data"] = None, {}

# ------------------------------------------------- 5. collect_installations (echte DB)
import sqlite3
db_path = os.environ["STARFACE_DB"]
if os.path.exists(db_path):
    os.remove(db_path)
conn = sqlite3.connect(db_path)
conn.execute("""CREATE TABLE installations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
    url TEXT NOT NULL, auth_id TEXT, auth_pass TEXT, client_secret TEXT,
    module_instance_name TEXT, monitoring_instance_name TEXT, is_starface10 INTEGER DEFAULT 0
)""")
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name) VALUES (?,?,?)",
             ("PBX-GUT", "http://gut", "TelefonieMonitoring"))
conn.execute("INSERT INTO installations (name, url, monitoring_instance_name) VALUES (?,?,?)",
             ("PBX-FAULT", FAULT_URL, "TelefonieMonitoring"))
conn.commit(); conn.close()

monitoring._get_token = lambda inst: "tok"
monitoring._xmlrpc = fake_xmlrpc
monitoring._state["last_values"].clear()
monitoring._state["last_error"] = None
writes = monitoring.collect_installations()
lv = monitoring._state["last_values"]
check("collect: PBX-GUT hat Modul-Liste (2, alles ok)",
      lv.get("PBX-GUT", {}).get("modules", {}).get("list")
      and all(i["status"] == "ok" for i in lv["PBX-GUT"]["modules"]["list"]),
      str(lv.get("PBX-GUT", {}).get("modules"))[:150])
check("collect: PBX-GUT systemName gesetzt",
      lv.get("PBX-GUT", {}).get("systemName") == "pbx", str(lv.get("PBX-GUT")))
m = lv.get("PBX-FAULT", {}).get("modules", {})
check("collect: PBX-FAULT -> module-Fehler (nicht installiert/eingerichtet)",
      m.get("error", {}).get("category") == "module"
      and m["error"]["msg"] == "Monitoring-Modul nicht installiert oder eingerichtet"
      and m.get("list") is None, str(m))
le = monitoring._state["last_error"]
check("collect: globaler last_error mit Kategorie module",
      le is not None and le.get("category") == "module" and "PBX-FAULT" in le.get("msg", ""), str(le))

monitoring._xmlrpc = real_xmlrpc

# ------------------------------------------------- 6. Render-Test monitoring.html
from main import TEMPLATES
base = {
    "running": True, "interval": 60, "influx_url": "http://x", "influx_bucket": "telefonie",
    "influx_configured": True, "last_run": 1787664390, "last_error": None,
    "total_runs": 42, "total_writes": 13,
    "installations": {
        "PBX-GUT": {
            "systemName": "pbx-gut", "systemVersion": "10.0.2.5", "ts": 1787664390, "points": 1,
            "modules": {"ts": time.time(), "error": None, "list": [
                {"name": "CallBlocker", "installed": True, "current": True, "status": "ok",
                 "version_ist": 28, "version_soll": 28, "vendor": "MiCoSa79",
                 "instances": [{"name": "CallBlocker", "active": True}]},
                {"name": "TelefonieMonitoring", "installed": True, "current": False, "status": "outdated",
                 "version_ist": 4, "version_soll": 5, "vendor": "MiCoSa79",
                 "instances": [{"name": "TelefonieMonitoring", "active": True}]},
            ]},
        },
        "PBX-FAULT": {
            "systemName": "pbx-fault", "systemVersion": "10.0.2.5", "ts": 1787664390, "points": 0,
            "modules": {"ts": time.time(),
                        "error": {"category": "module", "msg": "Monitoring-Modul nicht installiert oder eingerichtet"},
                        "list": None},
        },
        "PBX-MISSING": {
            "systemName": "pbx-missing", "systemVersion": "10.0.2.5", "ts": 1787664390, "points": 1,
            "modules": {"ts": time.time(), "error": None, "list": [
                {"name": "CallBlocker", "installed": False, "current": False, "status": "missing",
                 "version_ist": None, "version_soll": 28, "vendor": "MiCoSa79", "instances": []},
            ]},
        },
    },
}
html = TEMPLATES.env.get_template("monitoring.html").render(
    user={"username": "admin", "is_admin": True}, active="monitoring", status=base,
    id_by_name={n: i for i, n in enumerate(base["installations"])})
for marker in ["Modul-Status", 'id="mod-rows"',
               'title="Installierte Version entspricht der ausgelieferten."',
               'title="Auf der Anlage ist eine ältere Version installiert."',
               "Nicht installiert",
               "Monitoring-Modul nicht installiert oder eingerichtet", "— → v28"]:
    check(f"render: Marker '{marker}'", marker in html)
check("render: keine Emoji-Symbole in Modul-Badges",
      "✓" not in html and "✗" not in html and "⚠" not in html)
check("render: Instanz-Status in Zelle", "CallBlocker (aktiv)" in html)
check("render: Modul-Hinweis (mod-hint) + keine globale Fehlerbox ohne last_error",
      'class="mod-hint"' in html and 'class="errbox"' not in html)
for js in ["renderModuleRows(document.getElementById('mod-rows'), st.installations)",
           "function moduleBadge(it)", "function renderModuleRows(tbody, insts)"]:
    check(f"render: JS {js[:42]}...", js in html)

# Fehlerbox-Kategorie testen (letzter Fehler Kategorie module -> warn)
st_mod = dict(base, last_error={"msg": "PBX-FAULT: STARFACE-Fehler: xy", "ts": 1787664390,
                                "category": "module"})
html2 = TEMPLATES.env.get_template("monitoring.html").render(
    user={"username": "admin", "is_admin": True}, active="monitoring", status=st_mod,
    id_by_name={n: i for i, n in enumerate(base["installations"])})
check("render: Fehlerbox warn bei category module",
      'class="errbox errbox-warn"' in html2, "warn-Klasse fehlt in Fehlerbox")

# kein Modul-Datum -> Karte ohne Tabelle (No-JS-Fall)
base_leer = dict(base, installations={
    "PBX-X": {"systemName": "x", "ts": 1, "points": 0,
              "modules": {"ts": 1, "error": None, "list": []}},
})
html3 = TEMPLATES.env.get_template("monitoring.html").render(
    user={"username": "admin", "is_admin": True}, active="monitoring", status=base_leer,
    id_by_name={n: i for i, n in enumerate(base["installations"])})
check("render: ohne Modul-Daten Hinweistext statt Tabelle (kein Modul-Badge)",
      "Für keine Anlage liegen Modul-Status-Daten vor." in html3
      and 'id="tbl-mod"' not in html3
      and 'title="Installierte Version entspricht der ausgelieferten."' not in html3)

print()
if FAIL:
    print("FEHLER:", ", ".join(FAIL))
    sys.exit(1)
print("ALLE MODUL-STATUS-TESTS OK")
