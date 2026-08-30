"""Anlagen-Update-Scheduler (dm-v10): Ausführung fälliger Pläne + Zeitzonen.

Geprüft:
1. timeutil: Sommerzeit-Berechnung (2026-08-31T22:00 Berlin = 20:00 UTC)
2. timeutil: Winterzeit-Berechnung (2026-11-30T18:00 Berlin = 17:00 UTC)
3. timeutil: Anzeige-Roundtrip (UTC -> Europe/Berlin)
4. _run_due_plans: fälliger Plan (now - 60 s) -> executed, RPC mit Payload
5. _run_due_plans: überfälliger Plan (now - 600 s > GRACE 300) -> missed,
   KEIN RPC-Aufruf (kein stilles Nachholen)
6. _run_due_plans: zukünftiger Plan -> bleibt planned, kein RPC
7. _run_due_plans: inkonsistenter Zeitstempel -> übersprungen
8. _run_due_plans: RPC-Fehler -> status error + result-Meldung
9. _run_due_plans: Token-Fehler (Exception) -> error
10. _run_due_plans: leeres Token -> error

Aufruf: .venv/bin/python tmp_tests/anlagen_update_scheduler_test.py
"""
import base64
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/anlagen_update_scheduler_test/test.db"
if os.path.exists(DB):
    os.remove(DB)
os.makedirs(os.path.dirname(DB), exist_ok=True)
os.environ["STARFACE_DB"] = DB
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "test1234"
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()
for var in ("TOTP_ISSUER", "MODULE_UPDATE_BASE_URL", "UPDATE_SIGNING_SECRET",
            "ANLAGEN_UPDATE_TICK", "ANLAGEN_UPDATE_MISSED_GRACE"):
    os.environ.pop(var, None)

import main as app_main
import module_updates
import timeutil
import anlagen_update_scheduler as sched

app_main.init_db()
conn = sqlite3.connect(DB)
# Anlage (Direkt-INSERT reicht — Anlegen-Formular setzt Instanzen nicht)
conn.execute(
    "INSERT INTO installations (name, url, deployer_instance_name, deployer_token)"
    " VALUES ('SchedTest', 'https://schedtest.example', 'Deployment-Modul', 'tok-123')")
conn.commit()
conn.close()

FAIL = []


def check(name, cond, detail=""):
    print(("OK  " if cond else "FAIL") + f" {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def rpc_string(s):
    return ("<methodResponse><params><param><value><string>"
            + s + "</string></value></param></params></methodResponse>")


RPC_CALLS = []


def fake_xmlrpc(url, token, method, payload, instance_name=None):
    RPC_CALLS.append({"method": method, "payload": payload})
    if method == "ExecuteAnlagenUpdate":
        if payload.get("version") == "10.0.9.9":
            return {"raw": rpc_string("ERROR: Version 10.0.9.9 steht nicht in der Update-Liste")}
        return {"raw": rpc_string("OK: Update auf %s angestossen" % payload["version"])}
    raise AssertionError("unerwarteter RPC: " + method)


module_updates._xmlrpc = fake_xmlrpc
sched._get_token = lambda inst: "tok-123"

NOW = datetime(2026, 8, 30, 22, 0, 0, tzinfo=timezone.utc)  # fester Testzeitpunkt
INST = sqlite3.connect(DB).execute("SELECT id FROM installations LIMIT 1").fetchone()[0]


def insert_plan(scheduled_at_utc_iso):
    conn = sqlite3.connect(DB)
    cur = conn.execute(
        "INSERT INTO anlagen_update_plans (installation_id, version, update_url, scheduled_at)"
        " VALUES (?,?,?,?)",
        (INST, "10.0.3.0", "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
         scheduled_at_utc_iso))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def status_of(pid):
    return sqlite3.connect(DB).execute(
        "SELECT status, result FROM anlagen_update_plans WHERE id=?", (pid,)).fetchone()


def log_of(pid):
    # F108: Plan wird nach dem Ausführungsversuch GELÖSCHT — die Historie liegt
    # im anlagen_update_log (quelle='plan') mit plan_id-Referenz.
    return sqlite3.connect(DB).execute(
        "SELECT status, detail FROM anlagen_update_log"
        " WHERE plan_id=? ORDER BY id DESC LIMIT 1", (pid,)).fetchone()


# --- 1-3: Zeitzonen-Helfer ------------------------------------------------------
check("timeutil Sommerzeit 22:00 Berlin -> 20:00 UTC",
      timeutil.lokal_naive_zu_utc_iso("2026-08-31T22:00") == "2026-08-31T20:00:00+00:00")
check("timeutil Winterzeit 18:00 Berlin -> 17:00 UTC",
      timeutil.lokal_naive_zu_utc_iso("2026-11-30T18:00") == "2026-11-30T17:00:00+00:00")
check("timeutil ungültig -> None",
      timeutil.lokal_naive_zu_utc_iso("kaputt") is None)
check("timeutil Anzeige UTC -> Berlin (Sommer)",
      timeutil.utc_iso_zu_lokal_anzeige("2026-08-31T20:00:00+00:00") == "31.08.2026, 22:00 Uhr")
check("timeutil Anzeige UTC -> Berlin (Winter)",
      timeutil.utc_iso_zu_lokal_anzeige("2026-11-30T17:00:00+00:00") == "30.11.2026, 18:00 Uhr")

# --- 4: fälliger Plan -> executed -------------------------------------------------
pid = insert_plan((NOW - timedelta(seconds=60)).isoformat())
rpc_before = len(RPC_CALLS)
out = sched._run_due_plans(now=NOW)
check("Fällig: executed", any(s == "executed" for i, s, res in out if i == pid), str(out))
called = [x for x in RPC_CALLS[rpc_before:] if x["method"] == "ExecuteAnlagenUpdate"]
check("Fällig: RPC mit version+updateUrl+updateToken",
      bool(called) and called[0]["payload"] == {
          "version": "10.0.3.0",
          "updateUrl": "https://update.sub.example.de/stable/starface-10.0.3.0.rpm",
          "updateToken": "tok-123"}, str(called))
st = status_of(pid)
check("Fällig: Plan-Zeile GELÖSCHT", st is None, str(st))
lg = log_of(pid)
check("Fällig: Log pruefen (quelle=plan)", lg is not None and lg[0] == "pruefen", str(lg))

# --- 5: überfällig (> GRACE 300 s) -> missed, KEIN RPC ---------------------------
pid = insert_plan((NOW - timedelta(seconds=600)).isoformat())
rpc_before = len(RPC_CALLS)
out = sched._run_due_plans(now=NOW)
st = status_of(pid)
lg = log_of(pid)
check("Überfällig: Plan-Zeile GELÖSCHT", st is None, str(st))
check("Überfällig: Log fehlgeschlagen mit Hinweis",
      lg is not None and lg[0] == "fehlgeschlagen" and "nicht erreichbar" in (lg[1] or ""), str(lg))
check("Überfällig: KEIN RPC", len(RPC_CALLS) == rpc_before)

# --- 6: zukünftiger Plan -> bleibt planned ----------------------------------------
pid = insert_plan((NOW + timedelta(hours=2)).isoformat())
rpc_before = len(RPC_CALLS)
out = sched._run_due_plans(now=NOW)
st = status_of(pid)
check("Zukunft: planned", st[0] == "planned", str(st))
check("Zukunft: KEIN RPC", len(RPC_CALLS) == rpc_before)
# F110: partial unique index (planned) — den stehengebliebenen Plan aufräumen,
# damit der nächste Test neu planen darf (kein zweiter planned-Plan je Anlage).
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM anlagen_update_plans WHERE id=?", (pid,))
conn.commit()
conn.close()

# --- 7: kaputter Zeitstempel -> übersprungen ---------------------------------------
pid = insert_plan("nicht-parsebar")
rpc_before = len(RPC_CALLS)
out = sched._run_due_plans(now=NOW)
st = status_of(pid)
check("Kaputt: bleibt planned", st[0] == "planned", str(st))
check("Kaputt: KEIN RPC", len(RPC_CALLS) == rpc_before)
# F110: siehe Test 6 — Plan aufräumen
conn = sqlite3.connect(DB)
conn.execute("DELETE FROM anlagen_update_plans WHERE id=?", (pid,))
conn.commit()
conn.close()

# --- 8: RPC-Fehler -> error ---------------------------------------------------------
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url, scheduled_at)"
             " VALUES (?,?,?,?)",
             (INST, "10.0.9.9", "https://update.sub.example.de/stable/x.rpm",
              (NOW - timedelta(seconds=30)).isoformat()))
conn.commit()
pid = conn.execute("SELECT id FROM anlagen_update_plans ORDER BY id DESC LIMIT 1").fetchone()[0]
conn.close()
out = sched._run_due_plans(now=NOW)
st = status_of(pid)
lg = log_of(pid)
check("RPC-Fehler: Plan-Zeile GELÖSCHT", st is None, str(st))
check("RPC-Fehler: Log fehlgeschlagen mit Meldung",
      lg is not None and lg[0] == "fehlgeschlagen" and "nicht in der Update-Liste" in (lg[1] or ""),
      str(lg))

# --- 9: Token-Fehler (Exception) ------------------------------------------------------
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url, scheduled_at)"
             " VALUES (?,?,?,?)",
             (INST, "10.0.3.0", "https://update.sub.example.de/stable/x.rpm",
              (NOW - timedelta(seconds=30)).isoformat()))
conn.commit()
pid = conn.execute("SELECT id FROM anlagen_update_plans ORDER BY id DESC LIMIT 1").fetchone()[0]
conn.close()

def token_fail(inst):
    raise RuntimeError("OAuth-Token abgelaufen")

sched._get_token = token_fail
sched._run_due_plans(now=NOW)
st = status_of(pid)
lg = log_of(pid)
check("Token-Fehler: Plan-Zeile GELÖSCHT", st is None, str(st))
check("Token-Fehler: Log fehlgeschlagen mit Token-Hinweis",
      lg is not None and lg[0] == "fehlgeschlagen" and "Token-Fehler" in (lg[1] or ""), str(lg))
sched._get_token = lambda inst: "tok-123"

# --- 10: leeres Token -----------------------------------------------------------------
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url, scheduled_at)"
             " VALUES (?,?,?,?)",
             (INST, "10.0.3.0", "https://update.sub.example.de/stable/x.rpm",
              (NOW - timedelta(seconds=30)).isoformat()))
conn.commit()
pid = conn.execute("SELECT id FROM anlagen_update_plans ORDER BY id DESC LIMIT 1").fetchone()[0]
conn.close()

def token_leer(inst):
    return ""

sched._get_token = token_leer
sched._run_due_plans(now=NOW)
st = status_of(pid)
lg = log_of(pid)
check("Leeres Token: Plan-Zeile GELÖSCHT", st is None, str(st))
check("Leeres Token: Log fehlgeschlagen",
      lg is not None and lg[0] == "fehlgeschlagen" and "Kein gültiges OAuth-Token" in (lg[1] or ""),
      str(lg))

print()
if FAIL:
    print("FEHLGESCHLAGEN: " + ", ".join(FAIL))
    sys.exit(1)
print("ALLE CHECKS OK")
