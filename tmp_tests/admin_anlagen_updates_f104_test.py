"""F104 (v1.0.107): Geplante Updates liefen nie — Root Cause + Sichtbarkeit.

Live-Befund (30.08., Stack nightly, Plan id=5): result = "Token-Fehler: 'auth_id'"
→ der Scheduler-Query laden aus installations nur url/deployer_*; _get_token
braucht auth_id/auth_pass/client_secret/is_starface10/oauth_* → KeyError bei
JEDER geplanten Ausführung. In den Tests war _get_token gemockt → Blindstelle.

Geprüft:
1. ROOT: echte _get_token-Kette (Installation MIT Auth-Feldern + gültigem
   OAuth-Cache) → Plan wird 'executed' (ohne Fix: 'error'/'auth_id')
2. RPC-Fehler (ERROR-Antwort vom Deployer) → Plan 'error' UND Log
   'fehlgeschlagen' mit detail=result (vorher: keinerlei Spur)
3. überfällig (> GRACE) → 'missed' + Log 'fehlgeschlagen'
4. Template: Geplant-Seite zeigt bei error den result-Text sichtbar

Aufruf: .venv/bin/python tmp_tests/admin_anlagen_updates_f104_test.py
"""
import base64
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/anlagen_update_f104_test/test.db"
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
import anlagen_update_scheduler as sched

app_main.init_db()
conn = sqlite3.connect(DB)
# Installation A: Alte/ärmliche Form (wie im altTest-Setup) — nur für Template-Check
conn.execute(
    "INSERT INTO installations (name, url, deployer_instance_name, deployer_token)"
    " VALUES ('FehlerAnlage', 'https://fail.example', 'Deployment-Modul', 'tok-1')")
# Installation B: VOLLSTÄNDIG mit echten Fernet-verschlüsselten Auth-Feldern +
# gültigem OAuth-Cache (offline-fähig: starface_token gibt gecachten Token ohne Netz)
enc = lambda v: app_main._encrypt(v) if v else v
conn.execute(
    "INSERT INTO installations (name, url, auth_id, auth_pass, client_secret,"
    " is_starface10, oauth_access, oauth_refresh, oauth_expires,"
    " deployer_instance_name, deployer_token)"
    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
    ("VollAnlage", "https://voll.example",
     enc("auth1"), enc("pass1"), enc("secret1"), 1,
     enc("cached-access"), enc("cached-refresh"),
     int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp()),
     "Deployment-Modul", "tok-2"))
conn.commit()
A = conn.execute(
    "SELECT id FROM installations WHERE name='FehlerAnlage'").fetchone()[0]
B = conn.execute(
    "SELECT id FROM installations WHERE name='VollAnlage'").fetchone()[0]
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
sched._anlagen_version = lambda inst: "10.0.1.7"

NOW = datetime(2026, 8, 30, 22, 0, 0, tzinfo=timezone.utc)


def insert_plan(inst_id, scheduled_at_utc_iso, version="10.0.3.0"):
    conn = sqlite3.connect(DB)
    cur = conn.execute(
        "INSERT INTO anlagen_update_plans (installation_id, version, update_url, scheduled_at)"
        " VALUES (?,?,?,?)",
        (inst_id, version, "https://update.sub.example.de/stable/starface.rpm",
         scheduled_at_utc_iso))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def plan_of(pid):
    return sqlite3.connect(DB).execute(
        "SELECT status, result FROM anlagen_update_plans WHERE id=?",
        (pid,)).fetchone()


def log_of(plan_id):
    return sqlite3.connect(DB).execute(
        "SELECT status, detail, quelle FROM anlagen_update_log WHERE plan_id=?",
        (plan_id,)).fetchone()


# --- 1: ROOT CAUSE — echter _get_token gegen Installation B ----------------------
sched._get_token = app_main._get_token  # ECHT (kein Mock!) → beweist Query-Felder
pid = insert_plan(B, (NOW - timedelta(seconds=60)).isoformat())
out = sched._run_due_plans(now=NOW)
st, res = plan_of(pid)
check("ROOT: echtes _get_token ohne 'auth_id'-Kettenfehler",
      st == "executed" and "Token-Fehler" not in res, f"{st} — {res}")
check("ROOT: Log 'pruefen' angelegt (ok-Pfad unverändert)",
      log_of(pid) is not None and log_of(pid)[0] == "pruefen")

# --- 2: RPC-Fehler vom Deployer -> error + Log fehlgeschlagen --------------------
sched._get_token = lambda inst: "tok-123"  # Token ok — Fehler liegt im RPC
pid2 = insert_plan(B, (NOW - timedelta(seconds=30)).isoformat(), version="10.0.9.9")
out2 = sched._run_due_plans(now=NOW)
st2, res2 = plan_of(pid2)
lg2 = log_of(pid2)
check("RPC-Fehler: Plan error", st2 == "error", f"{st2} — {res2}")
check("RPC-Fehler: Log fehlgeschlagen mit detail",
      lg2 is not None and lg2[0] == "fehlgeschlagen"
      and "Update-Liste" in (lg2[1] or ""), str(lg2))

# --- 3: überfällig > GRACE -> missed + Log fehlgeschlagen ------------------------
pid3 = insert_plan(B, (NOW - timedelta(seconds=600)).isoformat())
out3 = sched._run_due_plans(now=NOW)
st3, res3 = plan_of(pid3)
lg3 = log_of(pid3)
check("Überfällig: missed", st3 == "missed", f"{st3} — {res3}")
check("Überfällig: Log fehlgeschlagen mit 'Scheduler war'",
      lg3 is not None and lg3[0] == "fehlgeschlagen"
      and "Scheduler war" in (lg3[1] or ""), str(lg3))

# --- 4: Template — result-Text auf der Geplant-Seite sichtbar --------------------
conn = sqlite3.connect(DB)
conn.execute(
    "INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
    " scheduled_at, status, result)"
    " VALUES (?,?,?,?,?,?)",
    (A, "10.0.2.5", "https://update.sub.example.de/x.rpm",
     (NOW - timedelta(seconds=60)).isoformat(), "error",
     "Token-Fehler: 'auth_id' (behoben) — Sichtbarkeits-Check"))
conn.commit()
conn.close()
acct = app_main.ProxyFix(app_main.app) if hasattr(app_main, "ProxyFix") else app_main.app
TESTER = type("T", (), {})()
try:
    from fastapi.testclient import TestClient
except ImportError:
    from starlette.testclient import TestClient
with TestClient(app_main.app) as client:
    r = client.post("/api/login",
                    data={"username": "admin", "password": "test1234"},
                    follow_redirects=False)
    g = client.get("/admin/anlagen-updates/geplant")
    html = g.text
    check("Template: Status 'Fehler' gerendert", "Fehler" in html)
    check("Template: result-Text sichtbar (kein stummer Fehler)",
          "auth_id" in html and "Sichtbarkeits-Check" in html)

print("=" * 40)
if FAIL:
    print(f"FAIL: {len(FAIL)} — {FAIL}")
    sys.exit(1)
print("ALLE F104-CHECKS OK")
