"""F108 (v1.0.111): Lebenszyklus „Geplant → Laufend → Durchgeführt".

Axels Anforderung (30.08.):
- „Geplante Updates" zeigt NUR wirklich geplante (status='planned'). Nach dem
  Ausführungsversuch (Trigger ok / Trigger-Fehler / verpasst) ist die Zeile weg.
- „Laufende Updates": Eintrag erscheint nach erfolgreichem Trigger mit
  Trigger-Status + Zeitpunkt + Herkunft (geplant); raus, sobald die Prüfung
  entschieden ist.
- „Durchgeführte Updates": pro Vorgang TRIGGER (Status + Zeitpunkt),
  PRÜFUNG (Status + Zeitpunkt — „—" wenn der Trigger fehlschlug) und
  GESAMTSTATUS + Fehlermeldung sichtbar.

Aufbau: Phase A (Scheduler) läuft OHNE TestClient — der Daemon-Thread tickt
alle 30 s und würde sonst Pläne klauen/prüfen. Phase B holt alle Seiten ab.
Benötigt: echte Zeiten (Log-Alter aus Delta abgeleitet) — gleiche Technik wie f96.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
import bcrypt
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from fastapi.testclient import TestClient  # noqa: E402

os.environ["STARFACE_DB"] = "/tmp/anlagen_update_f108_test/test.db"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "secret"
os.environ["FERNET_KEY"] = "5H4d2Qf3LyJ8xP6mN0bVcRzTkKwYhG1A7uEoI3sWnXq="
os.environ["MONITORING_ALPHA_PERIOD"] = "0"
os.environ["ANLAGEN_UPDATE_TICK"] = "30"
os.environ["ANLAGEN_UPDATE_CHECK_INTERVAL"] = "3600"
os.environ["ANLAGEN_UPDATE_CHECK_TIMEOUT"] = "3600"

DB = os.environ["STARFACE_DB"]
try:
    import shutil
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

def seed_user():
    pw = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
               ("admin", pw, 1))
    db.commit()
    db.close()

# Zwei Anlagen wie in Produktion (Systemstarface + Banner)
def seed_anlagen():
    db = sqlite3.connect(DB)
    db.execute("INSERT INTO installations"
               " (name, url, deployer_instance_name, deployer_token,"
               "  is_starface10, oauth_client) VALUES"
               " ('Alpha', 'https://anlage1.sub.example.de',"
               "  'Anlage1', 'tok1', 1, 'rest-client')")
    db.execute("INSERT INTO installations"
               " (name, url, deployer_instance_name, deployer_token,"
               "  is_starface10, oauth_client) VALUES"
               " ('Beta', 'https://anlage2.sub.example.de',"
               "  'Anlage2', 'tok2', 1, 'rest-client')")
    db.commit()
    db.close()

seed_user()
seed_anlagen()

# Anfangsbestand: kein Update-Log
assert sqlite3.connect(DB).execute("SELECT COUNT(*) FROM anlagen_update_log").fetchone()[0] == 0

# ── Mocks (Modulsymlink — Scheduler-Modul ist eigener Import, s. Kopf)
BUILD_ERR = {"status": "ERROR", "message": "ERROR: Version 10.0.9.9 steht nicht in der Update-Liste"}
BUILD_OK = {"status": "ok", "message": "Update läuft auf der Anlage"}

def fake_xmlrpc(uri, token, method, payload, **kw):
    if method == "ExecuteAnlagenUpdate":
        if payload.get("version") == "10.0.9.9":
            return {"raw": "<string>ERROR: Version 10.0.9.9 steht nicht in der Update-Liste</string>"}
        return {"raw": "<string>OK</string>"}
    raise AssertionError("unerwarteter RPC: " + str(method))
module_updates._xmlrpc = fake_xmlrpc

A = sqlite3.connect(DB).execute("SELECT id FROM installations WHERE name='Alpha'").fetchone()[0]
B = sqlite3.connect(DB).execute("SELECT id FROM installations WHERE name='Beta'").fetchone()[0]

# Scheduler-Aufrufe hinter denselben Modul-Grenzen mocken
sched._get_token = lambda inst: "tok-123"
sched._anlagen_version = lambda inst: "10.0.1.7"

NOW = datetime.now(timezone.utc)  # echte Zeit — der Scheduler-Thread tickt im
# Test mit und bliebe bei fiktiven Zeiten stehen; Log-Alter = echte Delta


def insert_plan(inst_id, version="10.0.3.0", scheduled_ago_s=60):
    db = sqlite3.connect(DB)
    cur = db.execute(
        "INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
        " scheduled_at, status) VALUES (?,?,?,?,'planned')",
        (inst_id, version, "https://update.sub.example.de/stable/starface.rpm",
         (NOW - timedelta(seconds=scheduled_ago_s)).isoformat(timespec="seconds")))
    db.commit()
    pid = cur.lastrowid
    db.close()
    return pid


def tbody(r):
    h = r.text
    return h[h.index("<tbody>"):h.index("</tbody>")]


def plan_of(pid):
    return sqlite3.connect(DB).execute(
        "SELECT id FROM anlagen_update_plans WHERE id=?", (pid,)).fetchone()


def logs_all():
    return sqlite3.connect(DB).execute(
        "SELECT id, installation_id, status FROM anlagen_update_log"
        " ORDER BY id").fetchall()


# ═══════════════════════ PHASE B1: Seiten-Check „Geplant" ═══════════════════
# Zukunftsplan (-1 h): auf „Geplant" sichtbar, aber NICHT fällig → der
# Daemon-Thread fasst ihn nicht an (kein Race mit dem Seiten-Check)
pid1 = insert_plan(A, scheduled_ago_s=-3600)
with TestClient(app_main.app) as client:
    r = client.post("/api/login", data={"username": "admin", "password": "secret"})
    check("Login", r.status_code == 200, str(r.status_code))

    g = client.get("/admin/anlagen-updates/geplant")
    h = g.text
    tb = tbody(g)
    check("1a Geplant: Plan-Zeile sichtbar (Anlage+Version+Uhrzeit)",
          "Alpha" in tb and "10.0.3.0" in tb and "Uhr" in tb and "abbrechen" in tb,
          tb[:300])
    check("1b Geplant: KEIN Löschen-Formular mehr (F108)",
          "geplant/loeschen" not in h and ">Löschen<" not in h)
# Client schließt → Daemon-Thread stoppt → Phase A ohne Race.
# Der Zukunftsplan war nur für den Seiten-Check — abräumen, damit die
# Geplant-Seite in Phase B2 nachweislich frei von erledigten Plänen ist.
db = sqlite3.connect(DB)
db.execute("DELETE FROM anlagen_update_plans WHERE id=?", (pid1,))
db.commit()
db.close()

# ═══════════════════════ PHASE A: Scheduler-Lebenszyklus ════════════════════
# ── 2: Trigger ok → Plan-Zeile weg, Laufend zeigt den Eintrag -----------------
pidT = insert_plan(A)
out2 = sched._run_due_plans(now=NOW)
check("2a Scheduler: Trigger ok", out2 and out2[0][1] == "executed", str(out2))
check("2b Plan-Zeile nach Trigger GELÖSCHT (Geplant leer)", plan_of(pidT) is None)
check("2c Log 'pruefen' angelegt (laufende Prüfung)",
      logs_all()[0][0] == 1 and logs_all()[0][2] == "pruefen", str(logs_all()))

# ── 3: Prüfung erfolgreich → raus aus Laufend, rein in Durchgeführt ----------
VERIFY_NOW = NOW + timedelta(minutes=90)  # Prüffenster abgelaufen
sched._anlagen_version = lambda inst: "10.0.3.0"  # Zielversion wurde installiert
ver = sched._verify_open_logs(now=VERIFY_NOW)
check("3a Verify: erfolgreich verbucht", ver and ver[0][1] == "erfolgreich", str(ver))
sched._anlagen_version = lambda inst: "10.0.1.7"  # zurück auf ALT für Abschnitt 4

# ── 4: Prüfung fehlgeschlagen (Ziel nicht erreicht) ---------------------------
pid4 = insert_plan(B)
out4 = sched._run_due_plans(now=NOW)
check("4a Trigger ok (Beta)", out4 and out4[0][1] == "executed", str(out4))
ver4 = sched._verify_open_logs(now=VERIFY_NOW)
check("4b Verify: fehlgeschlagen (Ziel nicht erreicht)",
      ver4 and ver4[0][1] == "fehlgeschlagen", str(ver4))

# ── 5: Prüfung unklar (Anlage nie erreichbar) → unbekannt --------------------
pid5 = insert_plan(B)
out5 = sched._run_due_plans(now=NOW)
check("5a Trigger ok (Beta 2)", out5 and out5[0][1] == "executed", str(out5))

def version_down(inst):
    raise RuntimeError("Verbindung zu Anlage fehlgeschlagen")

sched._anlagen_version = version_down
ver5 = sched._verify_open_logs(now=VERIFY_NOW)
check("5b Verify: unbekannt (nie erreichbar, kein Fehlurteil)",
      ver5 and ver5[0][1] == "unbekannt", str(ver5))

# ── 6: Trigger-Fehlschlag (RPC-ERROR) → SOFORT in Durchgeführt, keine Prüfung -
sched._anlagen_version = lambda inst: "10.0.1.7"  # Anlage wieder erreichbar
pid6 = insert_plan(A, version="10.0.9.9")
out6 = sched._run_due_plans(now=NOW)
check("6a Scheduler: Trigger-Fehler gemeldet (error + Meldung)",
      out6 and out6[0][1] == "error"
      and "nicht in der Update-Liste" in (out6[0][2] or ""), str(out6))
check("6b Plan-Zeile auch bei Fehlschlag GELÖSCHT", plan_of(pid6) is None)

# ═══════════════════════ PHASE B2: Seiten-Endzustände ══════════════════════
with TestClient(app_main.app) as client:
    client.post("/api/login", data={"username": "admin", "password": "secret"})

    g = client.get("/admin/anlagen-updates/geplant")
    tb = tbody(g)
    check("2b/6b Geplant: komplett leer (Trigger ok + Fehlschlag entfernt)",
          "Keine geplanten Updates" in tb, tb[:200])

    lfd = client.get("/admin/anlagen-updates/laufend")
    tb = tbody(lfd)
    check("3b Laufend: leer nach Erfolgsprüfung",
          "Keine laufenden Updates" in tb, tb[:200])

    dg = client.get("/admin/anlagen-updates/durchgefuehrt")
    tb = tbody(dg)
    check("3c Durchgeführt: Trigger ✓ + Zeit, Prüfung ✓ + Zeit, Gesamt erfolgreich",
          "✓ erfolgreich" in tb and "erfolgreich ·" in tb
          and "-erfolgreich-" in tb.replace(">", "-").replace("<", "-")
          and "Zielversion 10.0.3.0 bestätigt" in tb and "Uhr" in tb, tb[:500])
    check("4c Durchgeführt: Prüf-Fehlschlag — Trigger ok, Prüfung ✗ + Meldung",
          "✗" in tb and "fehlgeschlagen ·" in tb
          and "letzte gesehene Version" in tb and "(geplant)" in tb, tb[:500])
    check("5c Durchgeführt: Prüfung unbekannt — kein Fehlurteil",
          "unbekannt ·" in tb and "kein Urteil möglich" in tb, tb[:500])
    check("6c Durchgeführt: Trigger-Fehlschlag — Trigger ✗, Prüfung —, Meldung",
          "✗ fehlgeschlagen" in tb and "—" in tb
          and "nicht in der Update-Liste" in tb and "Uhr" in tb, tb[:500])
    check("6d Quelle korrekt markiert (alle 4 Vorgänge aus Planung)",
          tb.count("(geplant)") == 4, tb[:200])

# ═══════════════════════ PHASE C: Migration bereinigt Altbestand ════════════
# Altbestand (vor F108): executed + error + missed — werden beim Start gelöscht
db = sqlite3.connect(DB)
db.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
           " scheduled_at, status) VALUES (?, '10.0.2.5',"
           " 'https://update.sub.example.de/stable/starface.rpm',"
           " '2026-08-25T09:00:00+00:00', 'error')", (A,))
db.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
           " scheduled_at, status, ausgefuehrt_um) VALUES (?, '10.0.2.5',"
           " 'https://update.sub.example.de/stable/starface.rpm',"
           " '2026-08-24T09:00:00+00:00', 'executed',"
           " '2026-08-24T09:02:00+00:00')", (B,))
db.execute("INSERT INTO anlagen_update_plans (installation_id, version, update_url,"
           " scheduled_at, status) VALUES (?, '10.0.2.5',"
           " 'https://update.sub.example.de/stable/starface.rpm',"
           " '2026-08-23T09:00:00+00:00', 'missed')", (A,))
db.commit()
before = db.execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
db.close()
init_db()  # App-Start: F108-Migration
after = sqlite3.connect(DB).execute("SELECT COUNT(*) FROM anlagen_update_plans").fetchone()[0]
check("7a Migration: Altbestand (error/executed/missed) bereinigt",
      before == 3 and after == 0, f"{before} -> {after}")

print("\n" + ("ALLE CHECKS OK" if not FAILS else f"FAIL: {len(FAILS)} — {FAILS}"))
sys.exit(1 if FAILS else 0)
