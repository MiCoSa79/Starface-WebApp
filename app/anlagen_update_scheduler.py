"""Anlagen-Update-Scheduler (dm-v10): führt geplante STARFACE-Server-Updates aus.

Nutzer-Vorgabe Zeitzone (30.08.2026): Geplante Zeiten kommen aus der
Admin-UI als Europe/Berlin (datetime-local des Browsers) und werden IMMER
als UTC-ISO (timeutil.lokal_naive_zu_utc_iso) in der Tabelle
anlagen_update_plans gespeichert und verglichen — der Container läuft in
UTC, naive Zeitstempel würden beim Sommerzeit-Wechsel um 1–2 h kippen.

Status-Modell:
  planned   – wartet auf Ausführung
  executed  – ExecuteAnlagenUpdate-RPC ok (Update läuft auf der Anlage)
  error     – RPC-/Token-Fehler (Meldung in result)
  missed    – Fälligkeit lag beim Tick > MISSED_GRACE s zurück; bewusst KEIN
              stilles Nachholen (WebApp war down → Termin neu planen)
  cancelled – vom Admin abgebrochen

Der Daemon läuft als Thread im WebApp-Prozess (wie der Monitoring-Sammler),
prüft alle TICK Sekunden. Testbar: _run_due_plans(now) ist eine reine
Funktion auf der echten DB; RPC/Token werden über die Modul-Referenzen
(_db/_get_token/execute_anlagen_update) gemockt.
"""

import os
import threading
import time
from datetime import datetime, timezone

try:
    from main import _db, _get_token
    from module_updates import execute_anlagen_update
except ImportError:  # Container-Import (app.MODUL), Muster module_updates.py
    from app.main import _db, _get_token
    from app.module_updates import execute_anlagen_update

TICK = float(os.environ.get("ANLAGEN_UPDATE_TICK", "30"))
MISSED_GRACE = float(os.environ.get("ANLAGEN_UPDATE_MISSED_GRACE", "300"))


def _utc_zu_dt(s):
    try:
        return datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None


def _run_due_plans(now=None):
    """Führt alle fälligen Pläne (status='planned', scheduled_at <= now) aus.

    Rückgabe: Liste [(plan_id, status, result), ...] — Reihenfolge der
    fälligen Pläne. Für Tests: now übergeben, _db/_get_token/
    execute_anlagen_update mocken (Modul-Referenzen!).
    """
    now = now or datetime.now(timezone.utc)
    conn = _db()
    try:
        due = conn.execute(
            "SELECT p.*, i.name AS inst_name, i.url, i.deployer_instance_name,"
            " i.deployer_token"
            " FROM anlagen_update_plans p"
            " JOIN installations i ON i.id = p.installation_id"
            " WHERE p.status='planned' ORDER BY p.scheduled_at"
        ).fetchall()
    finally:
        conn.close()

    out = []
    for p in due:
        due_dt = _utc_zu_dt(p["scheduled_at"])
        if due_dt is None or due_dt > now:
            continue  # nicht fällig / kaputter Zeitstempel
        overdue = (now - due_dt).total_seconds()
        if overdue > MISSED_GRACE:
            new_status = "missed"
            result = ("Scheduler war zum geplanten Zeitpunkt nicht erreichbar"
                      f" (überfällig {int(overdue)} s, keine Nachhol-Logik).")
        else:
            try:
                token = _get_token(dict(p))
            except Exception as exc:  # Token-/Transportfehler → kontrolliert
                new_status, result = "error", f"Token-Fehler: {exc}"
            else:
                if not token:
                    new_status, result = "error", "Kein gültiges OAuth-Token der Anlage."
                else:
                    r = execute_anlagen_update(
                        dict(p), token, version=p["version"], update_url=p["update_url"])
                    if r.get("status") == "ok":
                        new_status, result = "executed", r.get("message", "ok")
                    else:
                        new_status, result = "error", r.get("message", "Unbekannter Fehler")
        c = _db()
        try:
            c.execute(
                "UPDATE anlagen_update_plans SET status=?, result=? WHERE id=? AND status='planned'",
                (new_status, str(result)[:500], p["id"]))
            c.commit()
        finally:
            c.close()
        out.append((p["id"], new_status, result))
    return out


def _loop():
    while True:
        try:
            _run_due_plans()
        except Exception:
            pass  # Der Scheduler darf niemals sterben (Log-Sparsamkeit)
        time.sleep(TICK)


_scheduler_thread = None


def start_scheduler():
    """Startet den Daemon-Thread (idempotent) — im Lifespan der WebApp."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _scheduler_thread = threading.Thread(
        target=_loop, name="anlagen-update-scheduler", daemon=True)
    _scheduler_thread.start()
