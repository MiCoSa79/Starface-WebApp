"""F110 (v1.0.114): Sicherheitsmechanismus für Anlagenupdates.

Axels Anforderung (30.08.):
- „Anlagen, für die bereits ein Update geplant ist, dürfen nicht nochmal ein
  Update geplant werden." → Variante C: App-Guard + Partial Unique Index.
- „Auch läuft gerade verhindert neues Update" — eine Anlage im
  pruefen-Zustand (anlagen_update_log) ist sowieso nicht abfragbar.
- Bulk: „Updates für die freien Anlagen planen. Meldung, welche Pläne
  angelegt wurden und welche nicht."
- Badges: „Update geplant für Datum" / „Update läuft gerade" auf
  Updates-einrichten, Anlagen-Detailseite und Anlagenübersicht.

Aufbau: TestClient ohne Scheduler-Daemon (ANLAGEN_UPDATE_TICK=86400 →
der Daemon fasst während des Tests keine Pläne an).
"""
import os
import sys
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
import bcrypt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from fastapi.testclient import TestClient  # noqa: E402

os.environ["STARFACE_DB"] = "/tmp/anlagen_update_f110_test/test.db"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["FERNET_KEY"] = "5H4d2Qf3LyJ8xP6mN0bVcRzTkKwYhG1A7uEoI3sWnXq="
os.environ["MONITORING_ALPHA_PERIOD"] = "0"
os.environ["ANLAGEN_UPDATE_TICK"] = "86400"  # Daemon tickt nicht während des Tests
os.environ["ANLAGEN_UPDATE_CHECK_INTERVAL"] = "3600"
os.environ["ANLAGEN_UPDATE_CHECK_TIMEOUT"] = "3600"

DB = os.environ["STARFACE_DB"]
try:
    shutil.rmtree(os.path.dirname(DB))
except OSError:
    pass
os.makedirs(os.path.dirname(DB), exist_ok=True)

import module_updates  # noqa: E402
import anlagen_update_scheduler as sched  # noqa: E402
import main as app_main  # noqa: E402
from main import init_db  # noqa: E402

init_db()

FAILS = []


def check(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name
          + (f" — {detail}" if (detail and not cond) else ""))
    if not cond:
        FAILS.append(name)


def seed_user(pw="secret"):
    ph = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
               ("admin", ph, 1))
    db.commit()
    db.close()


def seed_anlagen():
    db = sqlite3.connect(DB)
    for name, url in (("Alpha", "https://anlage1.sub.example.de"),
                      ("Beta", "https://anlage2.sub.example.de")):
        db.execute("INSERT INTO installations"
                   " (name, url, deployer_instance_name, deployer_token,"
                   "  is_starface10, oauth_client) VALUES (?,?,?,?,?,?)",
                   (name, url, "Deployer", "tok", 1, "rest-client"))
    db.commit()
    db.close()


def plan_count(installation_id=None):
    db = sqlite3.connect(DB)
    if installation_id is None:
        n = db.execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
    else:
        n = db.execute("SELECT COUNT(*) FROM anlagen_update_plans"
                       " WHERE installation_id=?", (installation_id,)).fetchone()[0]
    db.close()
    return n


def add_plan(installation_id, minutes_from_now=120):
    at = (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)
          ).replace(microsecond=0).isoformat()
    db = sqlite3.connect(DB)
    try:
        db.execute("INSERT INTO anlagen_update_plans"
                   " (installation_id, version, update_url, scheduled_at)"
                   " VALUES (?,?,?,?)",
                   (installation_id, "10.0.3.0", "http://updates.example/u.sfm", at))
        db.commit()
    finally:
        db.close()  # auch bei IntegrityError (5.2) schließen, sonst bleibt die DB gesperrt


def add_running_log(installation_id):
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO anlagen_update_log"
               " (installation_id, quelle, version_nach, angestossen_um, status)"
               " VALUES (?,?,?,?,?)",
               (installation_id, "direkt", "10.0.3.0", at, "pruefen"))
    db.commit()
    db.close()


seed_user()
seed_anlagen()

c = TestClient(app_main.app)
r = c.post("/api/login", data={"username": "admin", "password": "secret"})
assert r.status_code == 200 and r.json().get("status") == "ok", r.text

FUTURE = "2026-08-31T22:00"  # datetime-local (Europe/Berlin), in der Zukunft

def loc_of(r):
    """Location der 303-Redirects — msg ist quote()-encodiert → unquote."""
    from urllib.parse import unquote
    return unquote(r.history[0].headers.get("location", "")) if r.history else ""


def schedule(ids, version="10.0.3.0"):
    """POST /admin/anlagen-updates/schedule mit einer (Liste) von installation_id."""
    data = {"version": version, "update_url": "http://updates.example/u.sfm",
            "scheduled_for": FUTURE}
    if isinstance(ids, list):
        data["installation_ids"] = ids
    else:
        data["installation_ids"] = str(ids)
    return c.post("/admin/anlagen-updates/schedule", data=data)


# ── 1) Einzel: Anlage mit GELEGTEM Plan → kein zweiter Plan ──────────────
add_plan(1)
r = schedule(1)
# TestClient folgt Redirects automatisch → 303-Status + msg liegen in history[0]
loc = loc_of(r)
check("1.1 Einzel-blockiert: 303",
      bool(r.history) and r.history[0].status_code == 303,
      f"status={r.status_code} history={[h.status_code for h in r.history]}")
check("1.2 Einzel-blockiert: Meldung nennt bereits geplant",
      "bereits geplant" in loc, loc[:200])
check("1.3 Einzel-blockiert: weiterhin genau 1 Plan für Anlage 1",
      plan_count(1) == 1, f"count={plan_count(1)}")

# ── 2) Einzel: Anlage mit LAUFENDEM Update (pruefen) → kein Plan ─────────
add_running_log(2)
r = schedule(2)
loc = loc_of(r)
check("2.1 Laufend-blockiert: 303",
      bool(r.history) and r.history[0].status_code == 303)
check("2.2 Laufend-blockiert: Meldung nennt laufendes Update / nicht geplant",
      "läuft" in loc or "nicht geplant" in loc, loc[:200])
check("2.3 Laufend-blockiert: kein Plan für Anlage 2", plan_count(2) == 0,
      f"count={plan_count(2)}")

# ── 3) Einzel: freie Anlage → Plan wird angelegt ─────────────────────────
db = sqlite3.connect(DB)
db.execute("DELETE FROM anlagen_update_log WHERE installation_id=2")
db.commit()
db.close()
r = schedule(2, version="10.0.3.0")
loc = loc_of(r)
check("3.1 Einzel-frei: 303",
      bool(r.history) and r.history[0].status_code == 303)
check("3.2 Einzel-frei: Meldung 'geplant'",
      "geplant" in loc, loc[:200])
check("3.3 Einzel-frei: genau 1 Plan für Anlage 2", plan_count(2) == 1,
      f"count={plan_count(2)}")

# ── 4) Bulk: Anlage 1 belegt (Plan), Anlage 3 frei → nur freie planen ────
db = sqlite3.connect(DB)
db.execute("INSERT INTO installations"
           " (name, url, deployer_instance_name, deployer_token,"
           "  is_starface10, oauth_client) VALUES ('Gamma',?,?,?,?,?)",
           ("https://anlage3.sub.example.de", "Deployer", "tok", 1, "rest-client"))
db.commit()
db.close()
r = schedule([1, 3], version="10.0.3.0")
loc = loc_of(r)
check("4.1 Bulk teilbelegt: 303",
      bool(r.history) and r.history[0].status_code == 303)
check("4.2 Bulk teilbelegt: Anlage 1 NICHT doppelt geplant",
      plan_count(1) == 1, f"count={plan_count(1)}")
check("4.3 Bulk teilbelegt: Anlage 3 geplant",
      plan_count(3) == 1, f"count={plan_count(3)}")
check("4.4 Bulk teilbelegt: Meldung nennt Übersprungen/Gamma",
      "Gamma" in loc and "bersprungen" in loc.replace("Ü", "U"),
      loc[:250])

# ── 5) DB-Sicherheitsnetz: Partial Unique Index existiert + greift ───────
db = sqlite3.connect(DB)
idxs = [r[1] for r in db.execute("PRAGMA index_list(anlagen_update_plans)").fetchall()]
check("5.1 Unique-Index vorhanden",
      any("planned" in i.lower() or "einmalig" in i.lower() for i in idxs),
      str(idxs))
try:
    add_plan(3)  # Anlage 3 hat bereits einen planned-Plan (aus Test 4)
    dup = False
except sqlite3.IntegrityError:
    dup = True
check("5.2 Direkter Doppel-INSERT wirft IntegrityError", dup)
db.close()

# ── 6) Badges ────────────────────────────────────────────────────────────
# Anlage 1: geplant (aus Test 1) · Anlage 3: laufend? nein — laeuft-Test:
db = sqlite3.connect(DB)
db.execute("DELETE FROM anlagen_update_plans WHERE installation_id=1")
db.execute("INSERT INTO anlagen_update_plans"
           " (installation_id, version, update_url, scheduled_at)"
           " VALUES (1,'10.0.3.0','http://updates.example/u.sfm',?)",
           ((datetime.now(timezone.utc) + timedelta(hours=2)
             ).replace(microsecond=0).isoformat(),))
db.execute("INSERT INTO anlagen_update_log"
           " (installation_id, quelle, version_nach, angestossen_um, status)"
           " VALUES (3,'direkt','10.0.3.0',?, 'pruefen')",
           (datetime.now(timezone.utc).replace(microsecond=0).isoformat(),))
db.commit()
db.close()

r = c.get("/anlagen")
t = r.text
check("6.1 Übersicht: Badge 'Update geplant' für Anlage 1",
      "Update geplant" in t, "fehlt")
check("6.2 Übersicht: Badge 'Update läuft' für Anlage 3",
      "Update läuft" in t, "fehlt")

r = c.get("/installation/1")
t = r.text
check("6.3 Detailseite: Badge 'Update geplant'",
      "Update geplant" in t, "fehlt")
r = c.get("/installation/3")
t = r.text
check("6.4 Detailseite: Badge 'Update läuft'",
      "Update läuft" in t, "fehlt")

r = c.get("/admin/anlagen-updates")
t = r.text
check("6.5 Updates-einrichten: Badge 'Update geplant' (Anlage 1)",
      "Update geplant" in t, "fehlt")
check("6.6 Updates-einrichten: Badge 'Update läuft' (Anlage 3)",
      "Update läuft" in t, "fehlt")

# ── 7) Duplikat-Altbestand-Migration: zwei planned-Pläne → einer bleibt ──
# Achtung: DB_PATH ist eine Import-Konstante (Z. 38) — Env-Umstellung wirkt
# NICHT zur Laufzeit, also die Modul-Konstante direkt überschreiben.
DB2 = "/tmp/anlagen_update_f110_test/dup.db"
try:
    os.remove(DB2)
except OSError:
    pass
db2 = sqlite3.connect(DB2)
db2.execute("CREATE TABLE anlagen_update_plans ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " installation_id INTEGER NOT NULL,"
            " version TEXT NOT NULL, update_url TEXT NOT NULL,"
            " scheduled_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'planned',"
            " result TEXT DEFAULT '',"
            " created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
db2.execute("CREATE TABLE anlagen_update_log (id INTEGER PRIMARY KEY AUTOINCREMENT)")
at1 = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(microsecond=0).isoformat()
at2 = (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0).isoformat()
db2.execute("INSERT INTO anlagen_update_plans (installation_id,version,update_url,scheduled_at) VALUES (9,'10.0.1.0','u',?)", (at1,))
db2.execute("INSERT INTO anlagen_update_plans (installation_id,version,update_url,scheduled_at) VALUES (9,'10.0.2.0','u',?)", (at2,))
db2.commit()
db2.close()

app_main.DB_PATH = DB2
init_db()
db2 = sqlite3.connect(DB2)
n = db2.execute("SELECT COUNT(*) FROM anlagen_update_plans WHERE status='planned'"
                " AND installation_id=9").fetchone()[0]
idxs2 = [r[1] for r in db2.execute("PRAGMA index_list(anlagen_update_plans)").fetchall()]
db2.close()
app_main.DB_PATH = DB
check("7.1 Migration: Duplikat-Altbestand auf 1 Plan reduziert", n == 1, f"n={n}")
check("7.2 Migration: Unique-Index auf Alt-DB nach init_db",
      any("planned" in i.lower() or "einmalig" in i.lower() for i in idxs2),
      str(idxs2))

print()
if FAILS:
    print(f"{len(FAILS)} FAIL(S):")
    for f in FAILS:
        print(" -", f)
    sys.exit(1)
print("ALLE F110-CHECKS OK")
