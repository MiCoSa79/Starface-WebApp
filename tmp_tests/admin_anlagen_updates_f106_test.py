"""F106 (v1.0.109): Update-Verifikation hing als 'pruefen', obwohl das
Update durchlief — Root Cause in `_verify_open_logs`.

Live-Befund (30.08., Stack v1.0.107): „Das Update wurde erfolgreich
getriggert und ist durchgelaufen. Die Anlage ist längst wieder erreichbar.
Aber das Update steht immer noch unter laufende Updates."

Root Cause: die Query der Verifikation lädt aus installations nur
url/oauth_*/oauth_client — `_anlagen_version(dict(row))` → `_get_token`
greift auf auth_id/auth_pass/client_secret/is_starface10 zu → KeyError
(GLEICHE Falle wie F104, aber in _verify_open_logs) → except → ver='—' →
Zielversion wird NIE bestätigt; status bleibt 'pruefen' bis zur 60-Min-
Timebox, dann fälschlich 'unbekannt', obwohl die Anlage erreichbar ist
und längst auf der Zielversion läuft.

Geprüft (alles ECHTE _get_token/_anlagen_version-Kette, offline über
gültigen OAuth-Cache; nur _xmlrpc ist gefaked):
- L1 (Verifikation reif, Zielversion erreicht) → 'erfolgreich'
  + detail „Zielversion … bestätigt" (vorher: blieb 'pruefen')
- L2 (Timebox abgelaufen, Anlage erreichbar, Ziel NICHT erreicht)
  → 'fehlgeschlagen' + „letzte gesehene Version: 10.0.1.9"
  (vorher: 'unbekannt' — falsches Urteil bei erreichbarer Anlage)
- L3 (Bremse: jünger als CHECK_START_DELAY) → bleibt 'pruefen',
  kein RPC-Aufruf
- Insgesamt genau 2 GetStats-Aufrufe (L1 + L2)
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
os.environ["STARFACE_DB"] = "/tmp/f106_" + str(os.getpid()) + "/starface.db"
os.makedirs("/tmp/f106_" + str(os.getpid()), exist_ok=True)
import base64
os.environ["FERNET_KEY"] = base64.urlsafe_b64encode(b"x" * 32).decode()

import main as app_main
import module_updates
import anlagen_update_scheduler as sched
import monitoring  # _anlagen_version nutzt dessen _xmlrpc!

try:
    from main import _db, _encrypt
except ImportError:  # Repo-Strukturen
    from app.main import _db, _encrypt
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

app_main.init_db()
ok = True
now = datetime.now(timezone.utc)


def check(name, cond, extra=""):
    global ok
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        ok = False


def _insert_anlage(name, url):
    c = _db()
    try:
        c.execute(
            "INSERT INTO installations (name, url, auth_id, auth_pass, client_secret,"
            " is_starface10, module_instance_name, monitoring_instance_name,"
            " deployer_instance_name, deployer_token, oauth_access, oauth_refresh,"
            " oauth_expires)"
            " VALUES (?, ?, ?, ?, ?, 1, 'CallBlocker', 'Monitoring', 'Deployment',"
            " ?, ?, ?, ?)",
            (name, url, _encrypt("u:1"), _encrypt("pw"), _encrypt("cs"),
             _encrypt("tok"), _encrypt("at"), _encrypt("rt"),
             str(int(time.time()) + 3600)))
        c.commit()
        return c.execute("SELECT id FROM installations WHERE name=?", (name,)).fetchone()["id"]
    finally:
        c.close()


def _insert_log(inst_id, age_s, ziel, zuletzt_age_s):
    c = _db()
    try:
        c.execute(
            "INSERT INTO anlagen_update_log"
            " (installation_id, quelle, plan_id, version_vor, version_nach,"
            "  angestossen_um, status, zuletzt_um)"
            " VALUES (?, 'plan', 1, '10.0.1.7', ?, ?, 'pruefen', ?)",
            (inst_id, ziel,
             (now - timedelta(seconds=age_s)).isoformat(timespec="seconds"),
             (now - timedelta(seconds=zuletzt_age_s)).isoformat(timespec="seconds")))
        c.commit()
        return c.execute(
            "SELECT id FROM anlagen_update_log WHERE installation_id=? ORDER BY id DESC LIMIT 1",
            (inst_id,)).fetchone()["id"]
    finally:
        c.close()


xmlrpc_calls = {"n": 0}


def fake_xmlrpc(url, token, method, payload=None, instance_name=None):
    xmlrpc_calls["n"] += 1
    if method == "GetStats":
        # Anlage A (pbx1) hat die Zielversion erreicht, Anlage B (pbx2) nicht.
        version = "10.0.2.5" if "pbx1" in url else "10.0.1.9"
        return {"members": {"systemName": "Test", "systemVersion": version}}
    return {"status": "ok"}


for m in (module_updates, app_main, sched, monitoring):
    if hasattr(m, "_xmlrpc"):
        m._xmlrpc = fake_xmlrpc

# ---------------------------------------------------------------------------
# Anlagen + Logs
# ---------------------------------------------------------------------------
a = _insert_anlage("AnlageA", "http://pbx1.invalid")
b = _insert_anlage("AnlageB", "http://pbx2.invalid")

l1 = _insert_log(a, 600, "10.0.2.5", 400)      # reif, Ziel erreicht
l2 = _insert_log(b, 3601, "10.0.2.5", 400)     # Timebox abgelaufen, Ziel NICHT erreicht
l3 = _insert_log(a, 60, "10.0.2.5", 30)        # Bremse (zu jung)

res = sched._verify_open_logs(now)

r1 = next((r for r in res if r[0] == l1), None)
r2 = next((r for r in res if r[0] == l2), None)
r3 = next((r for r in res if r[0] == l3), None)

c = _db()
try:
    s1 = c.execute("SELECT status, detail FROM anlagen_update_log WHERE id=?",
                   (l1,)).fetchone()
    s2 = c.execute("SELECT status, detail FROM anlagen_update_log WHERE id=?",
                   (l2,)).fetchone()
    s3 = c.execute("SELECT status, detail FROM anlagen_update_log WHERE id=?",
                   (l3,)).fetchone()
finally:
    c.close()

check("F106/1 L1 -> erfolgreich (Zielversion bestätigt)",
      s1["status"] == "erfolgreich" and "Zielversion 10.0.2.5 bestätigt" in s1["detail"],
      f"status={s1['status']!r}")
check("F106/2 L2 -> fehlgeschlagen statt 'unbekannt' (Anlage erreichbar)",
      s2["status"] == "fehlgeschlagen" and "letzte gesehene Version: 10.0.1.9" in s2["detail"],
      f"status={s2['status']!r}, detail={s2['detail']!r}")
check("F106/3 L3 -> Bremse: bleibt 'pruefen'",
      s3["status"] == "pruefen", f"status={s3['status']!r}")
check("F106/4 genau 2 GetStats-Aufrufe (L1+L2; L3 gebremst)",
      xmlrpc_calls["n"] == 2, f"calls={xmlrpc_calls['n']}")

# ---------------------------------------------------------------------------
# F106b: ANSTOSS-Pfad (_run_due_plans) — version_vor über ECHTE Kette
# (F105-Nachbesserung: der Anstoß-Query lud kein monitoring_instance_name,
#  daher lieferte _anlagen_version IMMER '—' — erst der echte Ketten-Test
#  deckte es auf; der f105-Test mockte _anlagen_version → Blindstelle.)
# ---------------------------------------------------------------------------
c = _db()
try:
    c.execute(
        "INSERT INTO anlagen_update_plans"
        " (installation_id, version, update_url, scheduled_at, status)"
        " VALUES (?, '10.0.2.5', 'http://updates.invalid/anlage.sfp', ?, 'planned')",
        (b, (now - timedelta(seconds=60)).isoformat(timespec="seconds")))
    c.commit()
finally:
    c.close()

sched._run_due_plans(now)

c = _db()
try:
    plan = c.execute(
        "SELECT status, result FROM anlagen_update_plans"
        " WHERE installation_id=? ORDER BY id DESC LIMIT 1", (b,)).fetchone()
    log = c.execute(
        "SELECT status, version_vor FROM anlagen_update_log"
        " WHERE installation_id=? AND quelle='plan' ORDER BY id DESC LIMIT 1",
        (b,)).fetchone()
finally:
    c.close()

check("F106b/1 Plan-Zeile GELÖSCHT (F108 — Geplant zeigt nur planned)",
      plan is None, f"plan={plan!r}")
check("F106b/2 version_vor aus ECHTER Kette (10.0.1.9 statt '—')",
      log["status"] == "pruefen" and log["version_vor"] == "10.0.1.9",
      f"status={log['status']!r}, version_vor={log['version_vor']!r}")

print("---")
print("F106-TESTS:", "ALLE GRÜN" if ok else "FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
