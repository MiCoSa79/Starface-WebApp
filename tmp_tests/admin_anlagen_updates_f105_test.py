"""F105 (v1.0.108): (a) IST-Version VOR dem Anstoß + kein Update auf
unerreichbare Anlage; (b) Monitoring-Poll-Pause während laufender Updates.

Live-Befund (30.08.): "Version vorher" im Laufende-Updates-Screenshot war "—",
obwohl die App v10.0.1.7 kennt — der Scheduler holte GetStats erst NACH dem
ExecuteAnlagenUpdate-RPC; die Anlage startet sofort den Update-Prozess (Reboot)
→ GetStats schlug fehl. Zudem: "Letzter Fehler (17:06:05): Testanlage: Kein
gültiger Token verfügbar" auf der Startseite — der Sammler pollte mitten im
Update und verbuchte den Reboot als Token-Fehler.

Geprüft:
- F105a/1: _anlagen_version wirft (Anlage im Reboot) → Plan 'error'
  "Anlage vor Update nicht erreichbar" UND ExecuteAnlagenUpdate wird NICHT
  aufgerufen (vorher: Update wurde trotzdem gefeuert, version_vor "—")
- F105a/2: Erfolgsfall → anlagen_update_log.version_vor == IST-Version aus dem
  Pre-Check (GetStats VOR Execute; vorher "—")
- F105b/1: Anlage mit anlagen_update_log.status='pruefen' → Sammler macht
  KEINEN RPC (Token/GetStats unangetastet), kein last_error
- F105b/2: Alt-Fehler (last_error) wird durch den Skip-Zyklus gelöscht
  → nach Update-Ende heilt die Anzeige von selbst
- F105b/3: Nach Abschluss (status='erfolgreich') pollt der Sammler wieder

Aufruf: .venv/bin/python tmp_tests/admin_anlagen_updates_f105_test.py
"""
import base64
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/anlagen_update_f105_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET",
            "ANLAGEN_UPDATE_TICK", "ANLAGEN_UPDATE_MISSED_GRACE",
            "INFLUXDB_URL", "INFLUXDB_TOKEN"):
    os.environ.pop(var, None)

import main as app_main
import module_updates
import anlagen_update_scheduler as sched
import monitoring

app_main.init_db()
ok = True


def check(label, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        ok = False


def _db():
    return app_main._db()


def _encrypt(v):
    return app_main._encrypt(v)


def _insert_anlage(name="Testanlage"):
    c = _db()
    c.execute(
        "INSERT INTO installations"
        " (name, url, auth_id, auth_pass, client_secret, is_starface10,"
        "  module_instance_name, monitoring_instance_name,"
        "  deployer_instance_name, deployer_token, oauth_access,"
        "  oauth_refresh, oauth_expires)"
        " VALUES (?, ?, ?, ?, ?, 1, 'CallBlocker', 'Monitoring',"
        "         'Deployment', ?, ?, ?, ?)",
        (name, "http://pbx.invalid", _encrypt("u:1"), _encrypt("pw"),
         _encrypt("cs"), _encrypt("tok"), _encrypt("at"), _encrypt("rt"),
         str(int(time.time()) + 3600)))
    c.commit()
    return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _insert_plan(inst_id, scheduled_ago_s=300, version="10.0.2.5"):
    now = datetime.now(timezone.utc)
    c = _db()
    c.execute(
        "INSERT INTO anlagen_update_plans"
        " (installation_id, version, update_url, scheduled_at, status)"
        " VALUES (?, ?, ?, ?, 'planned')",
        (inst_id, version, "http://update.invalid/x",
         (now - timedelta(seconds=scheduled_ago_s))
         .isoformat(timespec="seconds")))
    c.commit()
    return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# ---------------------------------------------------------------------------
# F105a: Scheduler — GetStats VOR dem Anstoß
# ---------------------------------------------------------------------------
order = []
exec_calls = {"n": 0}


def stats_ok(inst):
    order.append("stats")
    return "10.0.1.7"


def stats_boom(inst):
    order.append("stats")
    raise RuntimeError("Connection refused (Reboot)")


def fake_xmlrpc(url, token, method, payload, instance_name=None):
    if method == "ExecuteAnlagenUpdate":
        order.append("execute")
        exec_calls["n"] += 1
        return {"status": "ok", "message": "ok"}
    return {"status": "ok", "message": "ok"}


sched._anlagen_version = stats_ok
sched._execute_anlagen_update = None  # nie erreicht; echter Rückweg über module_updates
module_updates._xmlrpc = fake_xmlrpc
sched._get_token = lambda inst: "tok-123"

# --- F105a/1: Anlage nicht erreichbar -> kein Update, sauberer Fehler ---
inst1 = _insert_anlage("DownAnlage")
plan1 = _insert_plan(inst1, scheduled_ago_s=60)
exec_calls["n"] = 0
order.clear()
sched._anlagen_version = stats_boom
sched._run_due_plans(datetime.now(timezone.utc))
c = _db()
p1 = c.execute("SELECT status, result FROM anlagen_update_plans WHERE id=?",
               (plan1,)).fetchone()
lg1 = c.execute(
    "SELECT status, detail, version_vor, version_nach FROM anlagen_update_log"
    " WHERE plan_id=?", (plan1,)).fetchone()
check("F105a/1 Plan = error", p1["status"] == "error")
check("F105a/1 result = 'Anlage vor Update nicht erreichbar'",
      "Anlage vor Update nicht erreichbar" in p1["result"])
check("F105a/1 ExecuteNICHT gerufen", exec_calls["n"] == 0)
check("F105a/1 Fehler-Log vorhanden", lg1 is not None and lg1["status"] == "fehlgeschlagen")
check("F105a/1 Log-detail = Pre-Check-Meldung",
      lg1 is not None and "nicht erreichbar" in lg1["detail"])
check("F105a/1 Log-version_vor = '—' (Anlage down, kein Wert verfügbar)",
      lg1 is not None and (lg1["version_vor"] or "—") in ("—", ""))

# --- F105a/2: Erfolgsfall -> version_vor aus dem Pre-Check, Reihenfolge ---
inst2 = _insert_anlage("VollAnlage")
plan2 = _insert_plan(inst2, scheduled_ago_s=60)
exec_calls["n"] = 0
order.clear()
sched._anlagen_version = stats_ok
sched._run_due_plans(datetime.now(timezone.utc))
c = _db()
p2 = c.execute("SELECT status FROM anlagen_update_plans WHERE id=?",
               (plan2,)).fetchone()
lg2 = c.execute(
    "SELECT status, version_vor FROM anlagen_update_log WHERE plan_id=?",
    (plan2,)).fetchone()
check("F105a/2 Plan = executed", p2["status"] == "executed")
check("F105a/2 execute gerufen", exec_calls["n"] == 1)
check("F105a/2 Reihenfolge GetStats VOR Execute",
      order == ["stats", "execute"])
check("F105a/2 version_vor = 10.0.1.7 (nicht '—')",
      lg2 is not None and lg2["version_vor"] == "10.0.1.7")
check("F105a/2 Log-status = pruefen", lg2 is not None and lg2["status"] == "pruefen")

# ---------------------------------------------------------------------------
# F105b: Monitoring-Sammler pausiert Anlagen mit laufendem Update
# ---------------------------------------------------------------------------
# Nur die Update-Anlage für den Monitoring-Teil übrig lassen — andere Anlagen
# ohne laufendes Update pollen normal (korrekt!) und würden die Zähler füllen.
c = _db()
c.execute("UPDATE installations SET monitoring_instance_name='' WHERE id IN (?, ?)",
          (inst1, inst2))
c.commit()

mon_calls = {"token": 0, "xmlrpc": 0}


def mon_token(inst):
    mon_calls["token"] += 1
    return "tok-123"


def mon_xmlrpc(url, token, method, payload=None, instance_name=None):
    mon_calls["xmlrpc"] += 1
    return {"members": {"systemName": "Testanlage",
                        "systemVersion": "10.0.1.7",
                        "providerStatus": ""}}


monitoring._get_token = mon_token
monitoring._xmlrpc = mon_xmlrpc
monitoring._write_points = lambda points: len(points)
monitoring._collect_module_status = (
    lambda inst, token, name, filter_third_party_missing=False:
    {"ts": time.time(), "list": []})

inst3 = _insert_anlage("UpdateAnlage")
c = _db()
c.execute(
    "INSERT INTO anlagen_update_log"
    " (installation_id, quelle, plan_id, version_vor, version_nach,"
    "  angestossen_um, status)"
    " VALUES (?, 'plan', NULL, '10.0.1.7', '10.0.2.5', ?, 'pruefen')",
    (inst3, datetime.now(timezone.utc).isoformat(timespec="seconds")))
c.commit()

# --- F105b/1: pruefen-Zeile -> kein Poll, kein Fehler ---
mon_calls["token"] = mon_calls["xmlrpc"] = 0
monitoring._state["last_error"] = None
monitoring.collect_installations()
check("F105b/1 kein Token-Aufruf (kein RPC)", mon_calls["token"] == 0)
check("F105b/1 kein GetStats-Aufruf", mon_calls["xmlrpc"] == 0)
check("F105b/1 kein last_error gesetzt",
      monitoring._state["last_error"] is None)

# --- F105b/2: Alt-Fehler (hier simuliert) wird vom Skip-Zyklus gelöscht ---
monitoring._state["last_error"] = {
    "msg": "Testanlage: Kein gültiger Token verfügbar", "ts": time.time()}
monitoring.collect_installations()
check("F105b/2 Alt-Fehler nach Skip-Zyklus gelöscht",
      monitoring._state["last_error"] is None)

# --- F105b/3: nach Abschluss pollt der Sammler wieder ---
c = _db()
c.execute("UPDATE anlagen_update_log SET status='erfolgreich'"
          " WHERE installation_id=?", (inst3,))
c.commit()
mon_calls["token"] = mon_calls["xmlrpc"] = 0
monitoring.collect_installations()
check("F105b/3 Poll wieder aktiv (Token gerufen)", mon_calls["token"] == 1)
check("F105b/3 GetStats wieder aktiv", mon_calls["xmlrpc"] >= 1)
check("F105b/3 Daten fließen wieder",
      monitoring._state["last_values"].get("UpdateAnlage", {})
      .get("systemVersion") == "10.0.1.7")

print("---")
print("F105-TESTS: " + ("ALLE GRÜN" if ok else "FEHLGESCHLAGEN"))
sys.exit(0 if ok else 1)
