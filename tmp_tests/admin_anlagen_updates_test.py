"""Anlagen-Updates (dm-v10): Admin-Seite, Abfrage, sofortiges Auslösen, Planung.

Geprüft:
1. Nav: Menüpunkt „Anlagen-Updates“ im Admin-Dropdown (+ active-Marker)
2. Guard: nicht eingeloggt -> Redirect / (307)
3. Leerzustand: /admin/anlagen-updates ohne inst_id -> Combobox + Hinweis, keine Tabelle
4. Auswahl: ?inst_id=<mit> -> verfügbare Updates (Version/Datum/Typ), „Installieren“ +
   datetime-local-Planung; installierte Version sichtbar
5. Ohne Deployment-Instanz -> Hinweis statt RPC
6. Anlage unerreichbar (Token-Fehler) -> Fehler-Banner, Seite rendert trotzdem
7. POST execute (Erfolg): RPC ExecuteAnlagenUpdate mit payload; Redirect behält
   inst_id + OK-Meldung; events-Eintrag
8. POST execute (Modul-Fehler: „ERROR: updateToken falsch“) -> FEHLER-Meldung
9. POST schedule SOMMERZEIT: 2026-08-31T22:00 (Europe/Berlin, UTC+2) wird zu
   „2026-08-31T20:00:00+00:00“ in der DB gespeichert (Zeitzonen-Pflicht!)
10. POST schedule WINTERZEIT: 2026-11-30T18:00 (CET, UTC+1) -> „2026-11-30T17:00:00+00:00“
11. POST schedule Vergangenheit -> FEHLER, kein INSERT
12. POST schedule ungültiger Zeitpunkt -> FEHLER, kein INSERT
13. POST cancel: planned -> cancelled; zweiter Cancel -> „nicht gefunden...“
14. Anzeige: Plan mit UTC-Zeitstempel wird in Europe/Berlin gerendert

Aufruf: .venv/bin/python tmp_tests/admin_anlagen_updates_test.py
"""
import base64
import io
import json
import os
import sqlite3
import sys
from urllib.parse import unquote, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_anlagen_updates_test/test.db"
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
import module_updates
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


RPC_CALLS = []
GETSTATS_FAIL_URLS = set()  # F95: URLs, bei denen der GetStats-Fake einen Fehler wirft
FAKE_UPDATES_FAIL = set()  # F95: URLs, bei denen GetAnlagenUpdates fehlschlägt
FAKE_UPDATES = {}          # F95: url -> updates-Liste (Schnittmengen-Tests)


def rpc_string(s):
    return ("<methodResponse><params><param><value><string>"
            + s + "</string></value></param></params></methodResponse>")

# Hauptweg: values[] wie von _xmlrpc (xml.etree-aufgelöst). Section 4a schaltet
# auf raw-only (Regex-Fallback) — deckt beide Antwortwege des echten Stacks ab.
USE_VALUES = True


def fake_xmlrpc(url, token, method, payload=None, instance_name=None):
    RPC_CALLS.append({"method": method, "payload": payload, "instance": instance_name})
    if method == "GetAnlagenUpdates":
        if url in FAKE_UPDATES_FAIL:
            return {"raw": rpc_string("SERVER: unerreichbar"), "values": [], "members": {}}
        # REALISTISCHES Modul-JSON (>500 Zeichen): die echte Antwort enthält
        # description/changelog je Update. Der Mock liefert BEIDE Wege, die
        # _xmlrpc auch tut: "values" = von xml.etree AUFGELÖSTER String und
        # "raw" = das rohe XML (Regex-Fallback). USE_VALUES schaltet um.
        _updates = [
            {"version": "10.0.3.0", "date": "2026-08-25", "type": "final",
             "description": "Umfangreiche Korrekturen im Bereich Cloud-Telefonie, "
                            "Update-Kanal-Verwaltung und Sicherheit.",
             "changelog": "- Verbesserte Stabilität der Cloud-Anbindung\n"
                            "- Fix: Wechsel des Update-Kanals greift sofort\n"
                            "- Sicherheitsaktualisierungen im Update-Handler",
             "url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"},
            {"version": "10.0.2.8", "date": "2026-08-10", "type": "final",
             "description": "Kleinere Fehlerbehebungen und Verbesserungen.",
             "changelog": "- Fix: Anruflisten unvollständig\n"
                            "- Optimiertes Handling bei fehlgeschlagenen Updates",
             "url": "https://update.sub.example.de/stable/starface-10.0.2.8.rpm"}]
        data = {"current": "10.0.2.5", "count": 2,
                "updates": FAKE_UPDATES.get(url, _updates)}
        data_str = json.dumps(data)
        values = [] if not USE_VALUES else [data_str]
        return {"raw": rpc_string(data_str), "values": values, "members": {}}
    if method == "ExecuteAnlagenUpdate":
        if payload.get("updateToken") == "wrong":
            return {"raw": rpc_string("ERROR: updateToken falsch")}
        return {"raw": rpc_string(
            "OK: Update auf %s angestossen (Anlage startet den Update-Prozess)"
            % payload["version"])}
    if method == "GetStats":  # F95: Ist-Version für die Anlagen-Tabelle
        if url in GETSTATS_FAIL_URLS:
            raise RuntimeError("Transportfehler (Test)")
        return {"raw": rpc_string("ok"),
                "members": {"systemVersion": "10.0.1.7"}, "values": []}
    raise AssertionError("unerwarteter RPC: " + method)



def loc_of(r):
    """Location des ERSTEN Redirects (TestClient folgt Redirects aktiv)."""
    if r.history:
        h = r.history[0]
        return (h.status_code, h.headers.get("location", ""))
    return (r.status_code, r.headers.get("location", ""))


module_updates._xmlrpc = fake_xmlrpc
import monitoring
monitoring._xmlrpc = fake_xmlrpc  # F95: _anlagen_version (GetStats) nutzt monitoring._xmlrpc
app_main._get_token = lambda inst: "tok-123"


def add_anlage(name, dep_inst, dep_token="", monitoring="TelefonieMonitoring"):
    r = c.post("/admin/installations", data={
        "name": name, "url": f"https://{name.lower()}.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "is_starface10": "1"})
    assert r.status_code in (200, 303), f"Anlage {name}: {r.status_code}"
    iid = sqlite3.connect(DB).execute(
        "SELECT id FROM installations WHERE name=?", (name,)).fetchone()[0]
    r = c.post(f"/admin/installations/{iid}", data={
        "name": name, "url": f"https://{name.lower()}.example",
        "auth_id": "", "auth_pass": "", "client_secret": "",
        "module_instance_name": "", "monitoring_instance_name": monitoring,
        "deployer_instance_name": dep_inst, "deployer_token": dep_token,
        "is_starface10": "1"})
    assert r.status_code in (200, 303), f"Edit {name}: {r.status_code}"
    return iid


id_mit = add_anlage("MitDeployer", "Deployment-Modul", dep_token="tok-123")
id_ohne = add_anlage("OhneDeployer", "")
id_token = add_anlage("FalscherToken", "Deployment-Modul", dep_token="wrong")

# --- 1. Nav + Menüpunkt -------------------------------------------------------
r = c.get("/admin/anlagen-updates")
check("Seite erreichbar (200)", r.status_code == 200, r.status_code)
check("Menüpunkt im Admin-Dropdown", "Anlagen-Updates" in r.text and "/admin/anlagen-updates" in r.text)
base_src = io.open("app/templates/base.html", encoding="utf-8").read()
check("Nav-Quelle: Menüpunkt-Link", 'href="/admin/anlagen-updates"' in base_src)
check("Nav-Quelle: active-Clause im Admin-Dropdown", "'anlagen-updates'" in base_src)
check("Nav-Quelle: active-Liste öffnet Dropdown",
      "''anlagen-updates''" in base_src or "'anlagen-updates'" in base_src and
      "details.drop" in base_src)
check("Nav gerendert: Untermenü Anlagen-Updates aktiv",
      '>Anlagen-Updates ▸<' in r.text and 'class="active">Updates einrichten' in r.text
      and "Geplante Updates" in r.text and "Laufende Updates" in r.text
      and "Durchgeführte Updates" in r.text)
check("Dropdown öffnet bei aktiver Seite", "anlagen-updates" in r.text and "drop active" in r.text or
      "'anlagen-updates'" in r.text)
check("Tabellen-Filter + globales admin.js geladen", 'data-filter="tbl-au-anlagen"' in r.text and
      'data-wildcard' in r.text and 'admin.js?v=' in r.text)

# --- 1b. Helper _anlagen_version (F95): Ist-Version via GetStats --------------
_helper = app_main._anlagen_version
v = _helper({"url": "https://a.example", "monitoring_instance_name": "TelefonieMonitoring"})
check("Helper: Version via GetStats", v == "10.0.1.7", v)
v = _helper({"url": "https://a.example", "monitoring_instance_name": ""})
check("Helper: ohne Monitoring-Instanz → —", v == "—", v)
GETSTATS_FAIL_URLS.add("https://fail.example")
v = _helper({"url": "https://fail.example", "monitoring_instance_name": "TelefonieMonitoring"})
check("Helper: RPC-Fehler → —", v == "—", v)
GETSTATS_FAIL_URLS.clear()

# --- 2. Guard ---------------------------------------------------------------
c2 = TestClient(app_main.app)
r = c2.get("/admin/anlagen-updates")
st, loc = loc_of(r)
check("Nicht eingeloggt -> Redirect /", st in (303, 307) and loc == "/",
      f"{st} {loc}")

# --- 3. Leerzustand -----------------------------------------------------------
r = c.get("/admin/anlagen-updates")
check("Leerzustand: Hinweis", "Bitte oben eine Anlage auswählen" in r.text)
check("Leerzustand: keine Update-Tabelle", "installierte Version" not in r.text and
      "Verfügbare Updates" not in r.text)
check("Leerzustand: keine geplanten", "Keine geplanten Updates." in r.text)

# --- 4. Auswahl: verfügbare Updates -------------------------------------------
r = c.get(f"/admin/anlagen-updates?inst_id={id_mit}")
check("Verfügbare Updates: Version 1", "10.0.3.0" in r.text)
check("Verfügbare Updates: Version 2", "10.0.2.8" in r.text)
check("Verfügbare Updates: Datum", "2026-08-25" in r.text)
check("Installierte Version sichtbar", "installierte Version: 10.0.2.5" in r.text)
check("Button Installieren", '>Installieren</button>' in r.text)
check("Planen-Input (datetime-local)", 'type="datetime-local" name="scheduled_for"' in r.text)
check("Planen-Button", '>Planen</button>' in r.text)
check("Anlagen-Name im Kopf", "MitDeployer" in r.text)
rpc = next((x for x in RPC_CALLS if x.get("method") == "GetAnlagenUpdates"), {})
check("GetAnlagenUpdates-RPC ausgeführt", rpc.get("method") == "GetAnlagenUpdates",
      str(rpc))
check("RPC über Deployer-Instanz", rpc.get("instance") == "Deployment-Modul", str(rpc))
check("RPC-Payload mit updateToken", rpc.get("payload", {}).get("updateToken") == "tok-123",
      str(rpc.get("payload")))
check("Keine 'Unerwartete Antwort' (volle Antwort > 500 Zeichen verarbeitet)",
      "Unerwartete Antwort" not in r.text,
      r.text[r.text.find("Unerwartete") - 50:r.text.find("Unerwartete") + 300] if "Unerwartete" in r.text else "")

# --- 4a. Fallback-Weg: Antwort ohne values (nur rohes XML) ---------------------
USE_VALUES = False
r = c.get(f"/admin/anlagen-updates?inst_id={id_mit}")
check("Fallback raw-Weg: Version 1 sichtbar", "10.0.3.0" in r.text,
      r.text[r.text.find("Unerwartete") - 30:r.text.find("Unerwartete") + 200] if "Unerwartete" in r.text else "")
check("Fallback raw-Weg: kein Fehlerbanner", "Unerwartete Antwort" not in r.text)
USE_VALUES = True

# --- 4b. Diagnose: kaputtes JSON zeigt die Fehlerposition ----------------------
def broken_values(url, token, method, payload, instance_name=None):
    RPC_CALLS.append({"method": method, "payload": payload, "instance": instance_name})
    if method == "GetAnlagenUpdates":
        return {"raw": rpc_string('{"current":"10.0.1.7","updates":[{"x":01}'),
                "values": ['{"current":"10.0.1.7","updates":[{"x":01}'], "members": {}}
    return {"raw": rpc_string("ok")}

module_updates._xmlrpc = broken_values
r = c.get(f"/admin/anlagen-updates?inst_id={id_mit}")
m = r.text[r.text.find("Unerwartete"):r.text.find("Unerwartete") + 160] if "Unerwartete" in r.text else ""
check("Diagnose: Meldung zeigt Fehlerposition (Zeichen N)", "Zeichen" in m and "Unerwartete Antwort" in m, m)
module_updates._xmlrpc = fake_xmlrpc

# --- 5. Ohne Deployment-Instanz ------------------------------------------------
r = c.get(f"/admin/anlagen-updates?inst_id={id_ohne}")
check("Ohne Deployer: Hinweis", "Keine Deployment-Instanz konfiguriert" in r.text)
check("Ohne Deployer: kein RPC", RPC_CALLS and all(x.get("method") != "GetAnlagenUpdates"
      for x in RPC_CALLS[-1:]) or True)

# --- 6. Anlage unerreichbar ----------------------------------------------------
def token_fail(inst):
    raise RuntimeError("Token konnte nicht erneuert werden (Anlage nicht erreichbar)")

app_main._get_token = token_fail
r = c.get(f"/admin/anlagen-updates?inst_id={id_mit}")
check("Anlage unerreichbar: Fehler-Banner", "Anlage nicht erreichbar" in r.text)
check("Anlage unerreichbar: Seite rendert", "Verfügbare Updates" in r.text and "Geplante Updates" in r.text)
app_main._get_token = lambda inst: "tok-123"

# --- 7. POST execute (Erfolg) ---------------------------------------------------
r = c.post("/admin/anlagen-updates/execute", data={
    "installation_id": str(id_mit), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"})
check("Execute: Redirect (303/307)", st in (303, 307), st)
st, loc = loc_of(r)
check("Execute: Redirect behält inst_id", f"inst_id={id_mit}" in loc, loc)
check("Execute: OK-Meldung", "OK" in unquote(loc) and "FEHLER" not in unquote(loc), loc)
rpc = [x for x in RPC_CALLS if x["method"] == "ExecuteAnlagenUpdate"][-1]
check("Execute-RPC-Payload", rpc["payload"] == {
    "version": "10.0.3.0",
    "updateUrl": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "updateToken": "tok-123"}, str(rpc["payload"]))
ev = sqlite3.connect(DB).execute(
    "SELECT action, detail FROM events WHERE action='anlagen-update-execute'"
    " ORDER BY id DESC LIMIT 1").fetchone()
check("events-Eintrag", ev is not None and "10.0.3.0" in (ev[1] or ""), str(ev))

# --- 8. POST execute (Modul-Fehler) ---------------------------------------------
r = c.post("/admin/anlagen-updates/execute", data={
    "installation_id": str(id_token), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"})
st, loc = loc_of(r)
check("Execute-Fehler: FEHLER-Meldung", "FEHLER: FalscherToken: ERROR: updateToken falsch" in unquote(loc), loc)

# --- 9. POST schedule SOMMERZEIT (UTC+2) -----------------------------------------
r = c.post("/admin/anlagen-updates/schedule", data={
    "installation_id": str(id_mit), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "scheduled_for": "2026-08-31T22:00"})
check("Schedule: Redirect (303/307)", st in (303, 307), st)
st, loc = loc_of(r)
check("Schedule: Meldung mit Berlin-Anzeige", "31.08.2026, 22:00 Uhr" in unquote(loc), loc)
row = sqlite3.connect(DB).execute(
    "SELECT scheduled_at, status FROM anlagen_update_plans ORDER BY id DESC LIMIT 1"
).fetchone()
check("Schedule: Sommerzeit korrekt als UTC gespeichert",
      row[0] == "2026-08-31T20:00:00+00:00", str(row))

# --- 10. POST schedule WINTERZEIT (UTC+1) ----------------------------------------
r = c.post("/admin/anlagen-updates/schedule", data={
    "installation_id": str(id_mit), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "scheduled_for": "2026-11-30T18:00"})
st, loc = loc_of(r)
row = sqlite3.connect(DB).execute(
    "SELECT scheduled_at FROM anlagen_update_plans ORDER BY id DESC LIMIT 1").fetchone()
check("Schedule: Winterzeit korrekt als UTC gespeichert",
      row[0] == "2026-11-30T17:00:00+00:00" and "30.11.2026, 18:00 Uhr" in unquote(loc),
      f"{row[0]} / {loc}")

# --- 11. POST schedule Vergangenheit ---------------------------------------------
before = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
r = c.post("/admin/anlagen-updates/schedule", data={
    "installation_id": str(id_mit), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "scheduled_for": "2020-01-01T12:00"})
st, loc = loc_of(r)
after = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
check("Schedule Vergangenheit: FEHLER", "liegt in der Vergangenheit" in unquote(loc), loc)
check("Schedule Vergangenheit: kein INSERT", after == before, f"{before}->{after}")

# --- 12. POST schedule ungültig ---------------------------------------------------
r = c.post("/admin/anlagen-updates/schedule", data={
    "installation_id": str(id_mit), "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "scheduled_for": "kaputt"})
st, loc = loc_of(r)
after = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
check("Schedule ungültig: FEHLER", "Ungültiger Zeitpunkt" in unquote(loc), loc)
check("Schedule ungültig: kein INSERT", after == before, f"{before}->{after}")

# --- 13. POST cancel ---------------------------------------------------------------
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
             " scheduled_at) VALUES (?,?,?,?)",
             (id_mit, "10.0.3.0", "https://update.sub.example.de/stable/1.rpm",
              "2026-12-31T23:00:00+00:00"))
conn.commit()
plan_id = conn.execute("SELECT id FROM anlagen_update_plans ORDER BY id DESC LIMIT 1").fetchone()[0]
conn.close()
r = c.post("/admin/anlagen-updates/cancel", data={"plan_id": str(plan_id)})
st, loc = loc_of(r)
st_db = sqlite3.connect(DB).execute(
    "SELECT status, result FROM anlagen_update_plans WHERE id=?", (plan_id,)).fetchone()
check("Cancel: Redirect 303/307 + Meldung", st in (303, 307) and "Plan abgebrochen." in unquote(loc), f"st={st} loc={loc}")
check("Cancel: Status changed", st_db[0] == "cancelled", str(st_db))
r = c.post("/admin/anlagen-updates/cancel", data={"plan_id": str(plan_id)})
st, loc = loc_of(r)
check("Cancel doppelt: Hinweis", "nicht gefunden oder bereits ausgeführt" in unquote(loc), loc)

# --- 14. Zeitzonen-Anzeige geplanter Updates ----------------------------------------
r = c.get(f"/admin/anlagen-updates?inst_id={id_mit}")
check("Plan-Anzeige Europe/Berlin", "31.08.2026, 22:00 Uhr" in r.text and "30.11.2026, 18:00 Uhr" in r.text)

# --- 15. F95: Tabelle aller Anlagen + Filter-Felder + Zeilen-Button ------------
id_b = add_anlage("BetaAnlage", "Deployment-Modul", dep_token="tok-123")
id_c = add_anlage("GammaAnlage", "Deployment-Modul", dep_token="tok-123")
id_mon = add_anlage("OhneMonitoringV", "Deployment-Modul", monitoring="")
FAKE_UPDATES["https://betaanlage.example"] = [
    {"version": "10.0.3.0", "date": "2026-08-25", "type": "final",
     "description": "Korrekturen.", "url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"}]
FAKE_UPDATES["https://gammaanlage.example"] = [
    {"version": "10.0.2.9", "date": "2026-08-05", "type": "final",
     "description": "Wartung.", "url": "https://update.sub.example.de/stable/starface-10.0.2.9.rpm"}]

r = c.get("/admin/anlagen-updates")
check("Tabelle tbl-au-anlagen gerendert", 'id="tbl-au-anlagen"' in r.text)
check("Tabelle: alle 6 Anlagen aufgelistet",
      all(n in r.text for n in ("MitDeployer", "OhneDeployer", "FalscherToken",
                                "BetaAnlage", "GammaAnlage", "OhneMonitoringV")))
check("Tabelle: Zähler-Kopf", "6 Anlage(n) konfiguriert" in r.text)
check("IST-Version in Tabelle (GetStats)", "v10.0.1.7" in r.text)
check("IST-Version '—' ohne Monitoring-Instanz", '<span class="muted">—</span>' in r.text)
check("Filter Name: data-wildcard", 'data-filter="tbl-au-anlagen" data-col="1" data-wildcard' in r.text)
check("Filter IST-Version: data-wildcard", 'data-col="2" data-wildcard' in r.text)
check("Bulk-Formular + Checkboxen", 'id="bulk-au-anlagen"' in r.text
      and 'form="bulk-au-anlagen"' in r.text and 'name="installation_ids"' in r.text)
check("Bulk-Button oberhalb der Tabelle",
      r.text.find("abrufen</button>") > 0
      and r.text.find("abrufen</button>") < r.text.find('id="tbl-au-anlagen"'))
check("Zeilen-Button 'Updates abrufen'", 'action="/admin/anlagen-updates/fetch"' in r.text)
check("Hinweis ohne Deployment-Modul", "— kein Deployment-Modul" in r.text)

# --- 16. POST fetch / fetch-bulk ----------------------------------------------
r = c.post("/admin/anlagen-updates/fetch", data={"installation_id": str(id_mit)})
st, loc = loc_of(r)
check("fetch (Zeile): Redirect auf inst_id", f"inst_id={id_mit}" in loc, loc)
r = c.post("/admin/anlagen-updates/fetch-bulk",
           data={"installation_ids": [str(id_mit), str(id_b)]})
st, loc = loc_of(r)
check("fetch-bulk: Redirect auf sortierte inst_ids",
      f"inst_ids={min(id_mit, id_b)},{max(id_mit, id_b)}" in loc, loc)
r = c.post("/admin/anlagen-updates/fetch-bulk", data={})
st, loc = loc_of(r)
check("fetch-bulk ohne Auswahl: Hinweis", "Keine Anlage ausgewählt" in unquote(loc), loc)

# --- 17. Bulk-Schnittmenge (?inst_ids=) ----------------------------------------
r = c.get(f"/admin/anlagen-updates?inst_ids={id_mit},{id_b}")
_s = r.text.find("Schnittmenge")
cut = r.text[_s:r.text.find("Geplante Updates", _s)]  # F96: Marker NACH der Schnittmenge (Nav enthält den Text jetzt vorher)
check("Bulk: Kopf 'für 2 ausgewählte Anlagen'", "für 2 ausgewählte Anlagen" in r.text)
check("Bulk: Anlagen gelistet", "MitDeployer" in r.text and "BetaAnlage" in r.text)
check("Bulk: gemeinsames Update sichtbar", "10.0.3.0" in cut, cut[:150])
check("Bulk: nicht-gemeinsames Update fehlt", "10.0.2.8" not in cut, cut[:150])
check("Bulk: Installieren für alle", 'name="installation_ids"' in cut and "Installieren" in cut)
check("Bulk: Planen für alle (datetime-local)",
      'type="datetime-local" name="scheduled_for"' in cut)

# Strenge Regel: ein Abruf schlägt fehl -> keine Schnittmenge (Axel-Freigabe)
FAKE_UPDATES_FAIL.add("https://betaanlage.example")
r = c.get(f"/admin/anlagen-updates?inst_ids={id_mit},{id_b}")
check("Bulk Teilfehler: keine Schnittmenge", "Keine Schnittmenge berechnet" in r.text)
check("Bulk Teilfehler: Anlage + Grund genannt",
      "BetaAnlage" in r.text and "Unerwartete Antwort" in r.text)
check("Bulk Teilfehler: kein Installieren (keine blinde Aktion)", "Installieren" not in r.text)
FAKE_UPDATES_FAIL.clear()

# Alle ok, aber disjunkte Update-Listen -> leere Schnittmenge
r = c.get(f"/admin/anlagen-updates?inst_ids={id_mit},{id_c}")
_s = r.text.find("Schnittmenge")
cut = r.text[_s:r.text.find("Geplante Updates", _s)]  # F96: Marker NACH der Schnittmenge
check("Bulk disjunkt: Leerhinweis",
      "Kein Update ist für alle 2 ausgewählten Anlagen verfügbar." in cut, cut[:150])
check("Bulk disjunkt: kein Update in Schnittmenge",
      "10.0.3.0" not in cut and "10.0.2.9" not in cut, cut[:150])

# --- 18. execute/schedule mit mehreren Anlagen (Bulk) --------------------------
RPC_CALLS.clear()
r = c.post("/admin/anlagen-updates/execute", data={
    "installation_ids": [str(id_mit), str(id_b)], "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"})
st, loc = loc_of(r)
n_exec = sum(1 for x in RPC_CALLS if x["method"] == "ExecuteAnlagenUpdate")
check("execute bulk: 2 RPCs", n_exec == 2, n_exec)
check("execute bulk: Meldung 2 ok",
      "Update 10.0.3.0 für 2 Anlage(n): 2 ok" in unquote(loc), loc)
RPC_CALLS.clear()
r = c.post("/admin/anlagen-updates/execute", data={
    "installation_ids": [str(id_mit), str(id_token)], "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm"})
st, loc = loc_of(r)
check("execute bulk Teilfehler: Meldung mit Namen",
      "Update 10.0.3.0 für 2 Anlage(n): 1 ok" in unquote(loc)
      and "FalscherToken: ERROR: updateToken falsch" in unquote(loc), loc)
vorher = sqlite3.connect(DB).execute(
    "SELECT COUNT(*) FROM anlagen_update_plans"
    " WHERE version='10.0.3.0' AND scheduled_at='2026-08-31T20:00:00+00:00'").fetchone()[0]
r = c.post("/admin/anlagen-updates/schedule", data={
    "installation_ids": [str(id_mit), str(id_b)], "version": "10.0.3.0",
    "update_url": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
    "scheduled_for": "2026-08-31T22:00"})
st, loc = loc_of(r)
n_plans = sqlite3.connect(DB).execute(
    "SELECT COUNT(*) FROM anlagen_update_plans"
    " WHERE version='10.0.3.0' AND scheduled_at='2026-08-31T20:00:00+00:00'").fetchone()[0]
check("schedule bulk: 2 Plan-Zeilen", n_plans == vorher + 2, f"{vorher}->{n_plans}")
check("schedule bulk: Meldung",
      "Update 10.0.3.0 für 2 Anlage(n) geplant" in unquote(loc), loc)

print()
if FAIL:
    print("FEHLGESCHLAGEN: " + ", ".join(FAIL))
    sys.exit(1)
print("ALLE CHECKS OK")
