"""F96 — Anlagen-Updates: Menü-Unterpunkte + Geplante/Laufende/Durchgeführte
Seiten + GetStats-Erfolgsprüfung (anlagen_update_log).

Geprüft:
A. DB: anlagen_update_log-Schema + Migration ausgefuehrt_um
B. _verify_open_logs: 5-Min-Bremse, Takt, erfolgreich (Zielversion), Timebox
   -> fehlgeschlagen (erreichbar) / unbekannt (nie erreichbar), fehlgeschlagen
   auch bei jetzt-down wenn früher gesehen
C. _run_due_plans: Plan-Ausführung legt Log-Zeile (quelle=plan) + ausgefuehrt_um
D. Routen: /geplant (Sortierung ASC, Abbrechen/Löschen), /laufend (Phase +
   Restzeit), /durchgefuehrt (Sortierung DESC, Badges, Quelle), POST
   abbrechen/loeschen, Guard Nicht-Admin, Menü 4 Unterpunkte, execute-Route
   legt Log-Zeile (quelle=direkt)

Aufruf: .venv/bin/python tmp_tests/admin_anlagen_updates_f96_test.py
"""
import base64
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

DB = "/tmp/admin_anlagen_updates_f96_test/test.db"
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
import anlagen_update_scheduler as aup
from starlette.testclient import TestClient

app_main.init_db()
import bcrypt
conn = sqlite3.connect(DB)
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("admin", bcrypt.hashpw(b"pw123", bcrypt.gensalt()).decode(), 1))
# Zwei Anlagen (Alpha mit Deployment, Beta ohne Deployment-Instanz)
conn.execute("INSERT INTO installations (name, url, deployer_instance_name,"
             " deployer_token, is_starface10, oauth_client)"
             " VALUES ('Alpha','http://alpha.example','Deployer','tok',1,'rest-client')")
conn.execute("INSERT INTO installations (name, url, deployer_instance_name,"
             " deployer_token, is_starface10, oauth_client)"
             " VALUES ('Beta','http://beta.example','','tok',1,'rest-client')")
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


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


NOW = datetime.now(timezone.utc)
ZIEL = "10.0.3.0"

# ── A: Schema ──────────────────────────────────────────────────────────────
conn = db()
lcols = {r[1] for r in conn.execute("PRAGMA table_info(anlagen_update_log)")}
conn.close()
for col in ("id", "installation_id", "quelle", "plan_id", "version_vor",
            "version_nach", "angestossen_um", "bestaetigt_um", "status",
            "version_zuletzt", "zuletzt_um", "detail"):
    check(f"A1 Log-Spalte {col}", col in lcols)
conn = db()
pcols = {r[1] for r in conn.execute("PRAGMA table_info(anlagen_update_plans)")}
conn.close()
check("A2 Migration ausgefuehrt_um", "ausgefuehrt_um" in pcols)

# ── B: _verify_open_logs ───────────────────────────────────────────────────
def insert_log(age_s, status="pruefen", version_zuletzt="", ziel=ZIEL, inst=1, vor="10.0.1.7"):
    conn = db()
    conn.execute(
        "INSERT INTO anlagen_update_log (installation_id, quelle, version_vor,"
        " version_nach, angestossen_um, status, version_zuletzt, zuletzt_um)"
        " VALUES (?, 'direkt', ?, ?, ?, ?, ?, '')",
        (inst, vor, ziel, (NOW - timedelta(seconds=age_s)).isoformat(timespec="seconds"),
         status, version_zuletzt))
    lid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return lid


def log_status(lid):
    conn = db()
    row = conn.execute("SELECT status, bestaetigt_um, version_zuletzt, detail"
                       " FROM anlagen_update_log WHERE id=?", (lid,)).fetchone()
    conn.close()
    return row


# b1 Bremse: 60 s alt -> kein Check (unter 5 Min)
lid = insert_log(60)
aup._anlagen_version = lambda inst: "10.0.2.5"
out = aup._verify_open_logs(now=NOW)
check("B1 Bremse: kein Urteil vor +5 min", out == [] and log_status(lid)["status"] == "pruefen",
      str(out))

# b2 erfolgreich: 10 Min alt, Ist == Ziel -> erfolgreich sofort
lid = insert_log(600)
aup._anlagen_version = lambda inst: ZIEL
out = aup._verify_open_logs(now=NOW)
st = log_status(lid)
check("B2 Zielversion bestätigt -> erfolgreich",
      out and out[0][1] == "erfolgreich" and st["status"] == "erfolgreich"
      and st["bestaetigt_um"] and "bestätigt" in st["detail"], str(out))

# b3 Takt + keine Urteil während Timebox: Ziel nicht erreicht, prüfen bleibt
lid = insert_log(600)
aup._anlagen_version = lambda inst: "10.0.2.5"
out1 = aup._verify_open_logs(now=NOW)
st1 = log_status(lid)
out2 = aup._verify_open_logs(now=NOW)
st2 = log_status(lid)
check("B3 Timebox läuft: bleibt pruefen + Erreichbarkeit notiert",
      out1[0][1] == "pruefen" and st1["status"] == "pruefen" and st1["version_zuletzt"] == "10.0.2.5",
      str(out1))
check("B3b Takt: zweiter Versuch <60 s wird übersprungen", out2 == [] and st2["status"] == "pruefen",
      str(out2))

# b4 fehlgeschlagen: 61 Min alt, Anlage erreichbar, Ziel nie erreicht
lid = insert_log(3660)
out = aup._verify_open_logs(now=NOW)
st = log_status(lid)
check("B4 Timebox um + erreichbar -> fehlgeschlagen",
      out and out[0][1] == "fehlgeschlagen" and "nicht erreicht" in st["detail"]
      and st["detail"].endswith("10.0.2.5"), str(out) + " | " + st["detail"])

# b5 unbekannt: 61 Min alt, Anlage NIE erreichbar gewesen
lid = insert_log(3660)
aup._anlagen_version = lambda inst: "—"
out = aup._verify_open_logs(now=NOW)
st = log_status(lid)
check("B5 Timebox um + nie erreichbar -> unbekannt (kein Fehlurteil)",
      out and out[0][1] == "unbekannt" and "nicht erreichbar" in st["detail"], str(out))

# b6 fehlgeschlagen trotz jetzt-down: früher war sie erreichbar (Version gesehen)
lid = insert_log(3660, version_zuletzt="10.0.2.5")
out = aup._verify_open_logs(now=NOW)
st = log_status(lid)
check("B6 früher erreichbar + jetzt down -> fehlgeschlagen, nicht unbekannt",
      out and out[0][1] == "fehlgeschlagen" and "letzte gesehene Version: 10.0.2.5" in st["detail"],
      str(out) + " | " + st["detail"])

# ── C: _run_due_plans legt Log an ─────────────────────────────────────────
conn = db()
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version,"
             " update_url, scheduled_at, status)"
             " VALUES (1, ?, 'u1', ?, 'planned')",
             (ZIEL, (NOW - timedelta(seconds=10)).isoformat(timespec="seconds")))
plan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
conn.commit()
conn.close()
aup._get_token = lambda inst: "tok"
aup.execute_anlagen_update = lambda inst, token, version, update_url: {
    "status": "ok", "message": "Update läuft auf der Anlage"}
aup._anlagen_version = lambda inst: "10.0.1.7"
out = aup._run_due_plans(now=NOW)
conn = db()
plan = conn.execute("SELECT status, ausgefuehrt_um FROM anlagen_update_plans"
                    " WHERE id=?", (plan_id,)).fetchone()
log = conn.execute("SELECT quelle, plan_id, version_vor, version_nach, status"
                   " FROM anlagen_update_log WHERE plan_id=?", (plan_id,)).fetchone()
conn.close()
check("C1 Trigger ok: Log pruefen + Plan-Zeile GELÖSCHT (aus Geplant entfernt)",
      out == [(plan_id, "executed", "Update läuft auf der Anlage")]
      and plan is None and log["status"] == "pruefen",
      str(out) + " plan=" + str(plan))
check("C2 Log-Zeile (quelle=plan, pruefen)", log
      and log["quelle"] == "plan" and log["plan_id"] == plan_id
      and log["version_vor"] == "10.0.1.7" and log["version_nach"] == ZIEL
      and log["status"] == "pruefen", str(log))

# Route-Mocks für D
SAVED_MAIN_VER = app_main._anlagen_version
app_main._anlagen_version = lambda inst: "10.0.1.7"

# ── D: Routen ──────────────────────────────────────────────────────────────
# Geplant: zwei Pläne (Beta 08:00, Alpha 06:00 UTC) -> Alpha zuerst (ASC)
conn = db()
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version,"
             " update_url, scheduled_at, status)"
             " VALUES (2, '10.0.2.5', 'u2', '2026-09-01T08:00:00+00:00', 'planned')")
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version,"
             " update_url, scheduled_at, status)"
             " VALUES (1, '10.0.2.5', 'u3', '2026-09-01T06:00:00+00:00', 'planned')")
# F108-Altbestand: erledigter Plan — wird von der Seite NICHT mehr angezeigt
conn.execute("INSERT INTO anlagen_update_plans (installation_id, version,"
             " update_url, scheduled_at, status, ausgefuehrt_um)"
             " VALUES (2, '10.0.2.5', 'u4', '2026-09-01T09:00:00+00:00', 'executed',"
             " '2026-09-01T09:02:00+00:00')")
conn.commit()
conn.close()

r = c.get("/admin/anlagen-updates/geplant")
h = r.text
check("D1 Seite Geplant rendert (nur geplante — Altbestand unsichtbar)",
      r.status_code == 200 and "Geplante Updates" in h
      and h.count(">Alpha<") == 1 and h.count(">Beta<") == 1, h[:1500])
check("D2 Sortierung ASC (nächstes fälliges oben)", h.index(">Alpha<") < h.index(">Beta<"))
check("D3 Nur Abbrechen — kein Löschen-Formular mehr (F108)",
      "geplant/abbrechen" in h and ">Abbrechen<" in h
      and "geplant/loeschen" not in h and ">Löschen<" not in h)

# Laufend: frischer Log (1 Min alt) -> Phase „startet ab +5 min" + Restzeit
lid = insert_log(60, inst=1)
r = c.get("/admin/anlagen-updates/laufend")
h = r.text
check("D4 Seite Laufend rendert", r.status_code == 200 and "Laufende Updates" in h
      and "Nachprüfung startet ab +5 min" in h and "min" in h and "10.0.1.7" in h)

# Durchgeführt: erfolgreich (Alpha, 10:00) + fehlgeschlagen (Beta, 09:00) -> DESC
conn = db()
conn.execute("INSERT INTO anlagen_update_log (installation_id, quelle, version_vor,"
             " version_nach, angestossen_um, status, bestaetigt_um, detail)"
             " VALUES (1, 'direkt', '10.0.1.7', '10.0.3.0',"
             " '2026-08-30T09:30:00+00:00', 'erfolgreich', '2026-08-30T10:00:00+00:00',"
             " 'Zielversion 10.0.3.0 bestätigt')")
conn.execute("INSERT INTO anlagen_update_log (installation_id, quelle, plan_id, version_vor,"
             " version_nach, angestossen_um, status, bestaetigt_um, detail)"
             " VALUES (2, 'plan', 1, '10.0.1.7', '10.0.2.5',"
             " '2026-08-30T08:30:00+00:00', 'fehlgeschlagen', '2026-08-30T09:00:00+00:00',"
             " 'Zielversion 10.0.2.5 bis 30.08. 09:00 nicht erreicht')")
# F108: trigger-Fehlschlag = fehlgeschlagen ohne bestaetigt_um (keine Prüfung)
conn.execute("INSERT INTO anlagen_update_log (installation_id, quelle, version_vor,"
             " version_nach, angestossen_um, status, detail)"
             " VALUES (1, 'direkt', '10.0.1.7', '10.0.3.0',"
             " '2026-08-30T08:00:00+00:00', 'fehlgeschlagen',"
             " 'Token-Fehler: OAuth-Token abgelaufen')")
conn.commit()
conn.close()

r = c.get("/admin/anlagen-updates/durchgefuehrt")
h = r.text
check("D5 Seite Durchgeführt rendert", r.status_code == 200
      and "Durchgeführte Updates" in h and ">erfolgreich<" in h and ">fehlgeschlagen<" in h)
# Drei D-Einträge + 5 abgeschlossene B-Logs (älter) — daher INHALTS-basiert prüfen
tb = h[h.index("<tbody>"):h.index("</tbody>")]
zeilen = [z for z in tb.split("<tr>")[1:] if "<td>" in z]


def zeile_mit(marker):
    return next((z for z in zeilen if marker in z), "")


zok = zeile_mit("Zielversion 10.0.3.0 bestätigt")
zb = zeile_mit(">Beta<")
zf = zeile_mit("Token-Fehler: OAuth-Token abgelaufen")
check("D6 F108-Zustände vorhanden (Erfolg / Prüf-Fehler / Trigger-Fehler)",
      bool(zok) and bool(zb) and bool(zf))
check("D7 Quelle geplant markiert (Trigger-Zelle)", "(geplant)" in zb
      and "(geplant)" not in zok)
check("D7b Erfolg: Trigger ok + Prüfung ok + Gesamt ok + Detail sichtbar",
      "✓ erfolgreich" in zok and "Zielversion 10.0.3.0 bestätigt" in zok)
check("D7c Prüf-Fehlschlag: Trigger ok, Prüfung ✗, Gesamt fehlgeschlagen + Meldung",
      "✓ erfolgreich" in zb and "✗" in zb and "fehlgeschlagen ·" in zb
      and "nicht erreicht" in zb)
check("D7d Trigger-Fehlschlag: Trigger ✗, Prüfung —, Fehlermeldung sichtbar",
      "✗ fehlgeschlagen" in zf and "Token-Fehler: OAuth-Token abgelaufen" in zf
      and "—" in zf)

# POST abbrechen (planned-Plan Beta -> id=2 in dieser DB: id=1 hat C verbraucht)
r = c.post("/admin/anlagen-updates/geplant/abbrechen", data={"plan_id": "2"},
           follow_redirects=False)
conn = db()
gone = conn.execute("SELECT id FROM anlagen_update_plans WHERE id=2").fetchone()
conn.close()
check("D8 Abbrechen planned -> DIREKT gelöscht (kein cancelled) + Redirect",
      r.status_code == 303 and "/anlagen-updates/geplant" in r.headers.get("location", "")
      and gone is None, f"location={r.headers.get('location')} gone={gone}")

# POST löschen (executed-Altbestand -> id=4); planned nicht löschbar (F108:
# Route bleibt aus Rückwärtskompatibilität, die Seite bietet kein Löschen mehr)
r = c.post("/admin/anlagen-updates/geplant/loeschen", data={"plan_id": "4"},
           follow_redirects=False)
conn = db()
gone = conn.execute("SELECT id FROM anlagen_update_plans WHERE id=4").fetchone()
conn.close()
check("D9 Löschen erledigter Eintrag (Route kompatibel)", r.status_code == 303 and gone is None,
      str(r.headers.get("location")))
# planned nicht löschbar: geplanter Alpha-Plan (id=3)
r = c.post("/admin/anlagen-updates/geplant/loeschen", data={"plan_id": "3"},
           follow_redirects=False)
conn = db()
still = conn.execute("SELECT id FROM anlagen_update_plans WHERE id=3").fetchone()
conn.close()
check("D10 planned nicht löschbar (erst abbrechen)", still is not None
      and "noch%20geplant" in r.headers.get("location", ""), r.headers.get("location"))

# Menü: 4 Unterpunkte im Admin-Dropdown
r = c.get("/")
h = r.text
for menue in ("Anlagen-Updates ▸", "Updates einrichten", "Geplante Updates",
              "Laufende Updates", "Durchgeführte Updates"):
    check(f"D11 Menüpunkt {menue}", menue in h)

# execute-Route legt Log an (quelle=direkt) — sofern die Route die Funktion
# aus module_updates importiert (Funktionskörper-Z 2569), reicht der Mock am
# Modul-Objekt; hasattr-Guard, falls der Importweg wechselt.
import module_updates
saved_exec_mu = module_updates.execute_anlagen_update
saved_exec_main = getattr(app_main, "execute_anlagen_update", None)
saved_token = app_main._get_token
FAKE_EXEC = lambda inst, token, version, update_url: {  # noqa: E731
    "status": "ok", "message": "Update läuft auf der Anlage"}
module_updates.execute_anlagen_update = FAKE_EXEC
if saved_exec_main is not None:
    app_main.execute_anlagen_update = FAKE_EXEC
app_main._get_token = lambda inst: "tok"
r = c.post("/admin/anlagen-updates/execute", data={"installation_ids": "1",
                                                   "version": "10.0.3.0",
                                                   "update_url": "u9"})
module_updates.execute_anlagen_update = saved_exec_mu
if saved_exec_main is not None:
    app_main.execute_anlagen_update = saved_exec_main
app_main._get_token = saved_token
conn = db()
log = conn.execute("SELECT quelle, version_vor, version_nach, status"
                   " FROM anlagen_update_log WHERE quelle='direkt'"
                   " ORDER BY id DESC LIMIT 1").fetchone()
conn.close()
print(">>> DEBUG direkte Logs:",
      [dict(x) for x in db().execute(
          "SELECT id, quelle, status FROM anlagen_update_log"
          " WHERE quelle='direkt' ORDER BY id DESC LIMIT 3").fetchall()])
check("D12 execute legt Log-Zeile an (direkt, pruefen)",
      log and log["quelle"] == "direkt" and log["version_vor"] == "10.0.1.7"
      and log["version_nach"] == "10.0.3.0" and log["status"] == "pruefen",
      "|||".join(str(k) + "=" + str(log[k]) for k in
                 ("quelle", "version_vor", "version_nach", "status")) if log else "kein Log")

app_main._anlagen_version = SAVED_MAIN_VER

# Guard: Nicht-Admin -> 307 auf /
u = c.post("/api/login", data={"username": "admin", "password": "pw123"})
conn = db()
conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?,?,?)",
             ("normal", bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(), 0))
conn.commit()
uid = conn.execute("SELECT id FROM users WHERE username='normal'").fetchone()[0]
conn.close()
r = c.post("/api/login", data={"username": "normal", "password": "pw"})
assert r.status_code == 200
for path in ("/admin/anlagen-updates/geplant", "/admin/anlagen-updates/laufend",
             "/admin/anlagen-updates/durchgefuehrt"):
    rr = c.get(path, follow_redirects=False)
    check(f"D13 Guard {path}", rr.status_code == 307 and
          rr.headers.get("location", "") in ("/", "http://testserver/"),
          str(rr.status_code) + " -> " + str(rr.headers.get("location")))

print()
if FAIL:
    print(f"FEHLGESCHLAGEN: {len(FAIL)} Checks — " + "; ".join(FAIL))
    sys.exit(1)
print("ALLE F96-CHECKS OK")
