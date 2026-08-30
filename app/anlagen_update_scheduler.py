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
    from main import _db, _get_token, _anlagen_version
    from module_updates import execute_anlagen_update
except ImportError:  # Container-Import (app.MODUL), Muster module_updates.py
    from app.main import _db, _get_token, _anlagen_version
    from app.module_updates import execute_anlagen_update

TICK = float(os.environ.get("ANLAGEN_UPDATE_TICK", "30"))
MISSED_GRACE = float(os.environ.get("ANLAGEN_UPDATE_MISSED_GRACE", "300"))
# F96: Erfolgsprüfung per GetStats — Bremse 5 Min (Update läuft auf der Anlage,
# PBX startet neu), danach je CHECK_INTERVAL s prüfen; Timebox 60 Min: vorher
# Schluss, sobald die Zielversion bestätigt ist (Axel-Vorgabe 30.08.).
CHECK_START_DELAY = float(os.environ.get("ANLAGEN_UPDATE_CHECK_START_DELAY", "300"))
CHECK_INTERVAL = float(os.environ.get("ANLAGEN_UPDATE_CHECK_INTERVAL", "60"))
CHECK_TIMEOUT = float(os.environ.get("ANLAGEN_UPDATE_CHECK_TIMEOUT", "3600"))


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
            "SELECT p.*, i.name AS inst_name, i.url, i.auth_id, i.auth_pass,"
            " i.client_secret, i.is_starface10, i.oauth_access, i.oauth_refresh,"
            " i.oauth_expires, i.deployer_instance_name, i.deployer_token"
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
                        # F96: Durchführungs-Log anlegen — die Erfolgsprüfung
                        # (GetStats-Vorher/Nachher) startet ab +5 Min.
                        try:
                            ver = _anlagen_version(dict(p)) or "—"
                        except Exception:
                            ver = "—"
                        c2 = _db()
                        try:
                            c2.execute(
                                "INSERT INTO anlagen_update_log"
                                " (installation_id, quelle, plan_id, version_vor,"
                                "  version_nach, angestossen_um, status)"
                                " VALUES (?, 'plan', ?, ?, ?, ?, 'pruefen')",
                                (p["installation_id"], p["id"], ver, p["version"],
                                 now.isoformat(timespec="seconds")))
                            c2.execute(
                                "UPDATE anlagen_update_plans SET ausgefuehrt_um=?"
                                " WHERE id=?",
                                (now.isoformat(timespec="seconds"), p["id"]))
                            c2.commit()
                        finally:
                            c2.close()
                    else:
                        new_status, result = "error", r.get("message", "Unbekannter Fehler")
        # F104: Fehlschläge nachvollziehbar machen — Log-Eintrag mit detail,
        # damit "Durchgeführte Updates" nie wieder leer bleibt, wenn etwas
        # schiefgeht (vorher bekam nur der ok-Pfad ein Log).
        if new_status in ("error", "missed"):
            try:
                ver = _anlagen_version(dict(p)) or "—"
            except Exception:
                ver = "—"
            c2 = _db()
            try:
                c2.execute(
                    "INSERT INTO anlagen_update_log"
                    " (installation_id, quelle, plan_id, version_vor,"
                    "  version_nach, angestossen_um, status, detail)"
                    " VALUES (?, 'plan', ?, ?, ?, ?, 'fehlgeschlagen', ?)",
                    (p["installation_id"], p["id"], ver, p["version"],
                     now.isoformat(timespec="seconds"), str(result)[:500]))
                c2.commit()
            finally:
                c2.close()
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


def _verify_open_logs(now=None):
    """Prüft offene Durchführungs-Logs (status='pruefen') gegen die Ist-Version.

    Axel-Vorgabe (F96): Nachprüfung beginnt erst CHECK_START_DELAY s (5 Min)
    nach dem Anstoß; weitere Versuche frühestens alle CHECK_INTERVAL s.
    Timebox CHECK_TIMEOUT (60 Min) — früher Schluss, sobald die Zielversion
    per GetStats bestätigt ist. Am Ende der Timebox: 'fehlgeschlagen', wenn die
    Anlage im Prüfzeitraum erreichbar war (Zielversion nie erreicht), sonst
    'unbekannt' (die ganze Zeit nicht erreichbar → kein Fehlurteil).

    Rückgabe: Liste [(log_id, new_status, detail), ...] — für Tests (now
    übergeben, _db/_anlagen_version am Modul mocken).
    """
    now = now or datetime.now(timezone.utc)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT l.*, i.name AS inst_name, i.url, i.oauth_access, i.oauth_refresh,"
            " i.oauth_expires, i.oauth_client"
            " FROM anlagen_update_log l JOIN installations i ON i.id = l.installation_id"
            " WHERE l.status='pruefen' ORDER BY l.angestossen_um"
        ).fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        start = _utc_zu_dt(row["angestossen_um"])
        if start is None:
            continue
        age = (now - start).total_seconds()
        if age < CHECK_START_DELAY:
            continue  # Bremse: Anlage arbeitet das Update noch ab
        prev = _utc_zu_dt(row["zuletzt_um"])
        if (prev is not None and row["status"] == "pruefen"
                and (now - prev).total_seconds() < CHECK_INTERVAL):
            continue  # Takt: nicht häufiger als CHECK_INTERVAL prüfen
        try:
            ver = _anlagen_version(dict(row))
        except Exception:
            ver = "—"
        ziel = row["version_nach"]
        now_iso = now.isoformat(timespec="seconds")
        if ver == ziel:
            new_status, detail = "erfolgreich", f"Zielversion {ziel} bestätigt"
            v_zuletzt, z_um, bestaetigt = ziel, now_iso, now_iso
        elif age >= CHECK_TIMEOUT and (ver != "—" or row["version_zuletzt"]):
            new_status, detail = "fehlgeschlagen", (
                f"Zielversion {ziel} bis {now.strftime('%d.%m. %H:%M')} nicht erreicht"
                + (f" — letzte gesehene Version: {ver}" if ver != "—"
                   else f" — letzte gesehene Version: {row['version_zuletzt']}"))
            v_zuletzt = ver if ver != "—" else row["version_zuletzt"]
            z_um = now_iso if ver != "—" else row["zuletzt_um"]
            bestaetigt = now_iso
        elif age >= CHECK_TIMEOUT:
            new_status, detail = "unbekannt", (
                "Anlage im Prüfzeitraum nicht erreichbar — kein Urteil möglich")
            v_zuletzt, z_um, bestaetigt = "", row["zuletzt_um"], now_iso
        else:
            new_status, detail, bestaetigt = "pruefen", "", ""
            v_zuletzt = ver if ver != "—" else row["version_zuletzt"]
            z_um = now_iso
        c = _db()
        try:
            c.execute(
                "UPDATE anlagen_update_log SET status=?, bestaetigt_um=?,"
                " version_zuletzt=?, zuletzt_um=?, detail=? WHERE id=?",
                (new_status, bestaetigt, v_zuletzt, z_um, str(detail)[:500], row["id"]))
            c.commit()
        finally:
            c.close()
        out.append((row["id"], new_status, detail))
    return out


def _loop():
    while True:
        try:
            _run_due_plans()
            _verify_open_logs()
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
